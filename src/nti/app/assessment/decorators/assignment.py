#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from collections import namedtuple

from datetime import datetime

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.location.interfaces import ILocation

from pyramid.interfaces import IRequest

from nti.app.assessment import VIEW_DELETE
from nti.app.assessment import VIEW_MOVE_PART
from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_INSERT_PART
from nti.app.assessment import VIEW_REMOVE_PART
from nti.app.assessment import VIEW_RESOLVE_TOPIC
from nti.app.assessment import VIEW_IS_NON_PUBLIC
from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_MOVE_PART_OPTION
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS
from nti.app.assessment import VIEW_INSERT_PART_OPTION
from nti.app.assessment import VIEW_REMOVE_PART_OPTION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS
from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION
from nti.app.assessment import VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD

from nti.app.assessment.common.evaluations import get_max_time_allowed
from nti.app.assessment.common.evaluations import is_global_evaluation
from nti.app.assessment.common.evaluations import get_evaluation_courses
from nti.app.assessment.common.evaluations import is_assignment_non_public_only
from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object
from nti.app.assessment.common.evaluations import get_available_assignments_for_evaluation_object

from nti.app.assessment.common.history import has_savepoints
from nti.app.assessment.common.history import get_most_recent_history_item

from nti.app.assessment.common.policy import get_policy_locked
from nti.app.assessment.common.policy import get_policy_excluded
from nti.app.assessment.common.policy import get_auto_grade_policy
from nti.app.assessment.common.policy import get_policy_full_submission
from nti.app.assessment.common.policy import get_policy_max_submissions
from nti.app.assessment.common.policy import get_submission_buffer_policy
from nti.app.assessment.common.policy import get_policy_submission_priority
from nti.app.assessment.common.policy import is_policy_max_submissions_unlimited
from nti.app.assessment.common.policy import get_policy_completion_passing_percent

from nti.app.assessment.common.submissions import has_submissions

from nti.app.assessment.common.utils import get_courses
from nti.app.assessment.common.utils import get_available_for_submission_ending
from nti.app.assessment.common.utils import get_available_for_submission_beginning

from nti.app.assessment.decorators import _root_url
from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate
from nti.app.assessment.decorators import InstructedCourseDecoratorMixin
from nti.app.assessment.decorators import decorate_assessed_values
from nti.app.assessment.decorators import decorate_question_solutions

from nti.app.assessment.interfaces import ISolutionDecorationConfig
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import assignment_download_precondition
from nti.app.assessment.utils import course_assignments_download_precondition

from nti.app.contentlibrary import LIBRARY_PATH_GET_VIEW

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.common import is_part_auto_gradable
from nti.assessment.common import is_randomized_question_set
from nti.assessment.common import is_randomized_parts_container

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQDiscussionAssignment
from nti.assessment.interfaces import IQuestionSetSubmission

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet
from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.completion.utils import get_completed_item

from nti.contenttypes.courses import get_course_vendor_info

from nti.contenttypes.courses.legacy_catalog import ILegacyCourseInstance

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor
from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.externalization.singleton import Singleton

from nti.links.links import Link

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid

from nti.traversal.traversal import find_interface

OID = StandardExternalFields.OID
LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


@component.adapter(ICourseInstance, IRequest)
@interface.implementer(IExternalMappingDecorator)
class _AssignmentsByOutlineNodeDecorator(AbstractAssessmentDecoratorPredicate):
    """
    For things that have a assignments, add this as a link.
    """

    # Note: This overlaps with the registrations in assessment_views
    # Note: We do not specify what we adapt, there are too many
    # things with no common ancestor. Those registrations are more general,
    # though, because we try to always go through a course, if possible
    # (because of issues resolving really old enrollment records), although
    # the enrollment record is a better place to go because it has the username
    # in the path

    def show_assignments_by_outline_link(self, course):
        """
        Returns a true value if the course should show the links [Non] assignments
        by outline node links
        """
        # We will remove when a preference course/user? policy is in
        # place.
        vendor_info = get_course_vendor_info(course, False) or {}
        try:
            result = vendor_info['NTI']['show_assignments_by_outline']
        except (TypeError, KeyError):
            result = True
        return result

    def _link_with_rel(self, course, rel):
        link = Link(course,
                    rel=rel,
                    elements=('@@' + rel,),
                    # We'd get the wrong type/ntiid values if we
                    # didn't ignore them.
                    ignore_properties_of_target=True)
        return link

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        course = ICourseInstance(context, context)

        links = result_map.setdefault(LINKS, [])
        for rel in ('NonAssignmentAssessmentItemsByOutlineNode',
                    'NonAssignmentAssessmentSummaryItemsByOutlineNode'):
            links.append(self._link_with_rel(course, rel))

        if self.show_assignments_by_outline_link(course):
            for rel in ('AssignmentsByOutlineNode',
                        'AssignmentSummaryByOutlineNode'):
                links.append(self._link_with_rel(course, rel))


@component.adapter(IQAssignment, IRequest)
@interface.implementer(IExternalMappingDecorator)
class _AssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    When an instructor fetches an assignment that contains a file part
    somewhere, provide access to the link to download it.
    """

    def _predicate(self, context, result):
        if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
            return assignment_download_precondition(context, self.request, self.remoteUser)

    def _do_decorate_external(self, context, result):
        links = result.setdefault(LINKS, [])
        course = _get_course_from_evaluation(context,
                                             self.remoteUser,
                                             request=self.request)
        if course is not None:
            ntiid = context.ntiid
            link = Link(course,
                        rel='ExportFiles',
                        elements=('Assessments', ntiid, '@@BulkFilePartDownload'))
        else:
            link = Link(context,
                        rel='ExportFiles',
                        elements=('@@BulkFilePartDownload',))
        links.append(link)


@component.adapter(ICourseInstance, IRequest)
@interface.implementer(IExternalObjectDecorator)
class _CourseAssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    Allow instructors and admins to download all file uploads for the course context.
    """

    def _predicate(self, context, result):
        if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
            return course_assignments_download_precondition(context, self.request)

    def _do_decorate_external(self, context, result):
        links = result.setdefault(LINKS, [])
        link = Link(context,
                    rel=VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD,
                    elements=('@@' + VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD,))
        links.append(link)


@component.adapter(IQAssignment, IRequest)
class _AssignmentOverridesDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    When an assignment is externalized, check for overrides.
    """

    @Lazy
    def _catalog(self):
        result = component.getUtility(ICourseCatalog)
        return result

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, assignment, result):
        course = _get_course_from_evaluation(assignment,
                                             self.remoteUser,
                                             self._catalog,
                                             request=self.request)
        if course is None:
            return

        # start date
        start_date = get_available_for_submission_beginning(assignment, course)
        ext_obj = to_external_object(start_date)
        result['available_for_submission_beginning'] = ext_obj

        # end date
        end_date = get_available_for_submission_ending(assignment, course)
        ext_obj = to_external_object(end_date)
        result['available_for_submission_ending'] = ext_obj

        if IQTimedAssignment.providedBy(assignment):
            max_time_allowed = get_max_time_allowed(assignment, course)
            result['IsTimedAssignment'] = True
            result['MaximumTimeAllowed'] = max_time_allowed
            result['maximum_time_allowed'] = max_time_allowed
        else:
            result['IsTimedAssignment'] = False

        # Max submissions
        result['max_submissions'] = get_policy_max_submissions(assignment, course)
        result['unlimited_submissions'] = is_policy_max_submissions_unlimited(assignment, course)
        result['completion_passing_percent'] = get_policy_completion_passing_percent(assignment, course)
        result['full_submission'] = get_policy_full_submission(assignment, course)
        result['submission_priority'] = get_policy_submission_priority(assignment, course)

        # auto_grade/total_points
        auto_grade = get_auto_grade_policy(assignment, course)
        if auto_grade:
            disabled = auto_grade.get('disable')
            # If we have policy but no disabled flag, default to True.
            result['auto_grade'] = not disabled if disabled is not None else True
            result['total_points'] = auto_grade.get('total_points')
        else:
            result['auto_grade'] = False
            result['total_points'] = None
        result['policy_locked'] = get_policy_locked(assignment, course)
        result['excluded'] = get_policy_excluded(assignment, course)
        result['submission_buffer'] = get_submission_buffer_policy(assignment, course)


@component.adapter(IQTimedAssignment, IRequest)
class _TimedAssignmentPartStripperDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _do_decorate_external(self, context, result):
        course = _get_course_from_evaluation(context,
                                             user=self.remoteUser,
                                             request=self.request)

        if     course is None \
            or is_course_instructor(course, self.remoteUser) \
            or has_permission(ACT_CONTENT_EDIT, course, self.request):
            return
        # Only return timed assignment parts if coming through a meta attempt item.
        # They've either started or have already submitted (non-instructor/editor).
        meta_item = IUsersCourseAssignmentAttemptMetadataItem(self.request, None)
        if meta_item is None:
            result['parts'] = None


class _AssignmentQuestionContentRootURLAdder(AbstractAuthenticatedRequestAwareDecorator):
    """
    When an assignment question is externalized, add the bucket root
    """

    def _do_decorate_external(self, context, result):
        ntiid = getattr(context, 'ContentUnitNTIID', None)
        if not ntiid:
            content_unit = find_interface(context, IContentUnit, strict=False)
            if content_unit is not None:
                ntiid = content_unit.ntiid
            else:
                assignment = find_interface(context,
                                            IQAssignment,
                                            strict=False)
                ntiid = getattr(assignment, 'ContentUnitNTIID', None)

        bucket_root = _root_url(ntiid) if ntiid else None
        if bucket_root:
            result['ContentRoot'] = bucket_root


class _AssignmentAfterDueDateSolutionDecorator(AbstractAuthenticatedRequestAwareDecorator,
                                               InstructedCourseDecoratorMixin):
    """
    We prevent exposing solutions and explanations during externalization,
    but will need to decorate them here for instructors and, if applicable,
    students.  For any assignment with a due date, this would be only after
    that date when a student has a submission.

    When we have a multiple submission assignment, we release solutions if
    the student has successfully completed the assignment.

    Instructors can also pick up solutions via externalizer selection
    in the view (e.g. when editing underlying parts directly, an
    externalizer is selected that exposes the solutions)
    """

    def should_decorate_assessment(self, context, course, user):
        result = True
        if      course is not None \
            and (   get_policy_max_submissions(context, course) > 1 \
                 or is_policy_max_submissions_unlimited(context, course)):
            # Ok, we can return solutions as long as they've successfully
            # completed the assignment (and it's multi-submission).
            completed_item = get_completed_item(user, course, context)
            result = completed_item is not None and completed_item.Success
        return result

    def needs_decorated(self, course, context, request, remoteUser):
        due_date = get_available_for_submission_ending(context, course)

        # By default, don't decorate
        result = False
        if not due_date or due_date <= datetime.utcnow():
            # If student check if there is a submission for the assignment
            if IQAssignment.providedBy(context):
                history_item = get_most_recent_history_item(remoteUser, course, context)
                # there is a submission
                if history_item is not None:
                    result = True
        return result

    def decorate(self,
                 question,
                 ext_question,
                 decorate_assessment=False,
                 is_randomized=False,
                 is_instructor=False):
        """
        Decorate solutions and explanation.
        """
        decorate_question_solutions(question,
                                    ext_question,
                                    is_randomized=is_randomized,
                                    is_instructor=is_instructor)

    def _is_randomized_qset(self, assessed_qset):
        return False

    def decorate_qset(self,
                      item,
                      ext_item,
                      decorate_assessment=True,
                      is_instructor=False):
        is_randomized_qset = self._is_randomized_qset(item)
        for q, ext_q in zip(getattr(item, 'questions', None) or (),
                            ext_item.get('questions') or ()):
            self.decorate(q,
                          ext_q,
                          decorate_assessment=decorate_assessment,
                          is_randomized=is_randomized_qset,
                          is_instructor=is_instructor)

    @property
    def _is_enabled_for_site(self):
        """
        Should solutions be decorated at all?  Some sites (e.g. SkillsUSA)
        don't want any solutions or indication of correctness presented to
        students (instructors would still need access)
        """
        config = component.queryUtility(ISolutionDecorationConfig)
        return config is None or config.ShouldExposeSolutions

    def _should_decorate(self, course, context, request, user):
        """
        We want to have different behavior if this is a max
        submission assignment. We'll decorate when they've
        successfully completed the assignment.
        """
        if not self._is_enabled_for_site:
            return False

        if course is None:
            return False

        if      course is not None \
            and (   get_policy_max_submissions(context, course) > 1 \
                 or is_policy_max_submissions_unlimited(context, course)):
            result = self.should_decorate_assessment(context, course, user)
        else:
            result = self.needs_decorated(course, context, request, user)
        return result

    def _assignment(self, context):
        return context

    def _predicate(self, context, _unused_result):
        assignment = self._assignment(context)
        auth_userid = self.authenticated_userid
        course = self.get_course(assignment, auth_userid, self.request)

        if not bool(auth_userid) or course is None:
            return False

        self._is_instructor = self.is_instructor(course, self.request)
        return (self._is_instructor
                or self._should_decorate(course,
                                         assignment,
                                         self.request,
                                         self.remoteUser))

    def _do_decorate_external(self, context, result):
        for part, ext_part in zip(getattr(context, 'parts', None) or (),
                                  result.get('parts') or ()):
            question_set = ext_part.get('question_set')
            if question_set:
                self.decorate_qset(part.question_set, question_set,
                                   is_instructor=self._is_instructor)


class _NonInstructorStripAssignmentPartsAfterSubmission(AbstractAuthenticatedRequestAwareDecorator,
                                                        InstructedCourseDecoratorMixin):
    """
    For enrolled users with *any* submissions, always strip the assignment parts.
    This is not on by default.
    """

    def _should_strip(self, course, context, request, remoteUser):
        history_item = get_most_recent_history_item(remoteUser, course, context)
        return history_item is not None

    def _do_decorate_external(self, context, result):
        course = self.get_course(context, self.remoteUser, self.request)
        if self.is_instructor(course, self.request):
            return
        if self._should_strip(course, context, self.request, self.remoteUser):
            result.pop('parts', None)
        result['HideAfterSubmission'] = True


class _AssignmentSubmissionPendingAssessmentAfterDueDateSolutionDecorator(_AssignmentAfterDueDateSolutionDecorator):
    """
    We prevent exposing assessedValue during externalization,
    but will need to decorate it here for instructors or, if applicable,
    students.  For any assignment with a due date, this would be only after
    that date when a student has a submission.  Also decorates solutions
    and explanations, when applicable and handles any necessary
    randomization of those solution for students.

    When we have a multiple submission assignment, we release solutions if
    the student has successfully completed the assignment.
    """

    def _assignment(self, context):
        return component.queryUtility(IQAssignment, context.assignmentId)

    def _is_randomized_qset(self, assessed_qset):
        # Should be False for instructors
        qset = find_object_with_ntiid(assessed_qset.questionSetId)
        return IRandomizedPartsContainer.providedBy(qset)

    def _assn_question(self, context):
        question_id = context.questionId or ''
        return component.queryUtility(IQuestion, name=question_id)

    def decorate(self,
                 question,
                 ext_question,
                 decorate_assessment=False,
                 is_randomized=False,
                 is_instructor=False):
        """
        Decorate solutions and explanation. Also, decorates correctness
        (if available)
        """
        assn_question = self._assn_question(question)
        _AssignmentAfterDueDateSolutionDecorator.decorate(
            self,
            assn_question,
            ext_question,
            decorate_assessment=decorate_assessment,
            is_randomized=is_randomized,
            is_instructor=is_instructor)
        if decorate_assessment or is_instructor:
            decorate_assessed_values(question, ext_question)

    def _do_decorate_external(self, context, result):
        assg = self._assignment(context)
        course = self.get_course(assg, self.remoteUser, self.request)
        decorate_assessment = self.should_decorate_assessment(assg, course, self.remoteUser)
        is_instructor = self.is_instructor(course, self.request)
        for part, ext_part in zip(getattr(context, 'parts', None) or (),
                                  result.get('parts') or ()):
            if not IQuestionSetSubmission.providedBy(part):
                self.decorate_qset(part,
                                   ext_part,
                                   decorate_assessment=decorate_assessment,
                                   is_instructor=is_instructor)


@interface.implementer(IExternalObjectDecorator)
class _QuestionSetDecorator(Singleton):

    def decorateExternalObject(self, original, external):
        oid = getattr(original, 'oid', None)
        if oid and OID not in external:
            external[OID] = oid


@interface.implementer(IExternalObjectDecorator)
class _AssignmentPartDecorator(Singleton):
    """
    The underlying QuestionSet may not always be externalized, so
    decorate the QuestionSetId on externalization for clients.
    """

    def decorateExternalObject(self, original, external):
        if original.question_set is not None:
            external['QuestionSetId'] = original.question_set.ntiid


@interface.implementer(IExternalObjectDecorator)
class QuestionSetRandomizedDecorator(Singleton):
    """
    Decorate the randomized state of question sets, since links may not be
    present.
    """

    def decorateExternalObject(self, original, external):
        external['Randomized'] = is_randomized_question_set(original)
        external['RandomizedPartsType'] = is_randomized_parts_container(original)


_ContextStatus = namedtuple("_ContextStatus",
                            ("has_savepoints", "has_submissions", "is_available"))


@interface.implementer(IExternalMappingDecorator)
class _AssessmentEditorDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    Give editors editing links on IQEditableEvaluations. A subset of
    links should only be available for IQEditableEvaluations that do
    not have submissions. Also provide context on whether the evaluation
    has been savepointed/submitted.
    """

    _MARKER_RELS = (VIEW_MOVE_PART, VIEW_INSERT_PART, VIEW_REMOVE_PART,
                    VIEW_MOVE_PART_OPTION, VIEW_INSERT_PART_OPTION,
                    VIEW_REMOVE_PART_OPTION, VIEW_DELETE, VIEW_IS_NON_PUBLIC)

    def get_courses(self, context):
        result = set()
        courses = get_evaluation_courses(context)
        for course in courses or ():
            hierarchy = get_courses(course)
            result.update(hierarchy)
        return result

    def _has_edit_link(self, _links):
        for lnk in _links:
            if getattr(lnk, 'rel', None) == 'edit':
                return True
        return False

    def _is_available(self, context):
        assignments = get_available_assignments_for_evaluation_object(context)
        return bool(assignments)

    def _predicate(self, context, unused_result):
        # `IQDiscussionAssignment` objects are handled elsewhere.
        return  self._is_authenticated \
            and not IQDiscussionAssignment.providedBy(context) \
            and has_permission(ACT_CONTENT_EDIT, context, self.request)

    def _get_question_rels(self):
        """
        Gather any links needed for a non-in-progress editable questions.
        """
        return (VIEW_MOVE_PART,
                VIEW_INSERT_PART,
                VIEW_REMOVE_PART,
                VIEW_MOVE_PART_OPTION,
                VIEW_INSERT_PART_OPTION,
                VIEW_REMOVE_PART_OPTION,
                VIEW_DELETE)

    def _get_assignment_rels(self, context, courses):
        """
        Gather any links needed for a non-in-progress editable assignments.
        """
        result = [VIEW_MOVE_PART, VIEW_INSERT_PART,
                  VIEW_REMOVE_PART, VIEW_DELETE]
        if self._can_toggle_is_non_public(context):
            result.append(VIEW_IS_NON_PUBLIC)
        return result

    def _get_question_set_rels(self, context):
        """
        Gather any links needed for a non-in-progress editable question sets.
        """
        rels = []
        rels.append(VIEW_DELETE)
        rels.append(VIEW_QUESTION_SET_CONTENTS)
        rels.append(VIEW_ASSESSMENT_MOVE)

        # Question banks cannot be (un)randomized since we may
        # support ranges.
        if not IQuestionBank.providedBy(context):
            if IRandomizedQuestionSet.providedBy(context):
                rels.append(VIEW_UNRANDOMIZE)
            else:
                rels.append(VIEW_RANDOMIZE)

        if IRandomizedPartsContainer.providedBy(context):
            rels.append(VIEW_UNRANDOMIZE_PARTS)
        else:
            rels.append(VIEW_RANDOMIZE_PARTS)
        return rels

    def _get_context_status(self, context, courses):
        """
        Retrieve our contextual status regarding student visiblity,
        savepoints, and submissions.
        """
        # We need to check assignments for our context for submissions.
        assignments = get_containers_for_evaluation_object(context)
        savepoints = is_available = False
        for assignment in assignments:
            savepoints = savepoints or has_savepoints(assignment, courses)
            is_available = is_available or self._is_available(assignment)
        submissions = has_submissions(context, courses)
        return _ContextStatus(has_savepoints=savepoints,
                              has_submissions=submissions,
                              is_available=is_available)

    def _can_toggle_is_non_public(self, context):
        """
        It can be toggled only if it is not in progress and all of its
        contained courses are not ForCredit only. We don't yet have a way to
        determine if a course is Public only.
        """
        return not is_assignment_non_public_only(context)

    def _do_decorate_external(self, context, result):
        _links = result.setdefault(LINKS, [])

        courses = self.get_courses(context)
        context_status = self._get_context_status(context, courses)
        in_progress = context_status.has_savepoints or context_status.has_submissions
        result['IsAvailable'] = context_status.is_available
        result['LimitedEditingCapabilities'] = in_progress
        result['LimitedEditingCapabilitiesSavepoints'] = context_status.has_savepoints
        result['LimitedEditingCapabilitiesSubmissions'] = context_status.has_submissions

        if IQAssignment.providedBy(context):
            # For assignments, we want to decorate the insertable status
            # when the clients fetch only the summary of the objects. This
            # allows behavior to be dictated even if the client does not have
            # the full object.
            result['CanInsertQuestions'] = not in_progress

        rels = ['schema',]
        # We provide the edit link no matter the status of the assessment
        # object. Some edits (textual changes) will be allowed no matter what.
        if not self._has_edit_link(_links):
            rels.append('edit')

        if not in_progress:
            # Do not provide structural links if evaluation has savepoints
            # or submissions.
            if IQuestionSet.providedBy(context):
                qset_rels = self._get_question_set_rels(context)
                if qset_rels:
                    rels.extend(qset_rels)
            elif IQAssignment.providedBy(context):
                rels.extend(self._get_assignment_rels(context, courses))
            elif IQuestion.providedBy(context):
                rels.extend(self._get_question_rels())

        # chose link context according to the presence of a course
        start_elements = ()
        course = get_course_from_request(self.request)
        link_context = context if course is None else course
        if course is not None:
            start_elements = ('Assessments', context.ntiid)

        # loop through rels and create links
        for rel in rels:
            if rel in self._MARKER_RELS:
                elements = None if not start_elements else start_elements
            else:
                elements = start_elements + ('@@%s' % rel,)
            link = Link(link_context, rel=rel, elements=elements)
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = link_context
            _links.append(link)


@interface.implementer(IExternalMappingDecorator)
class _DiscussionAssignmentEditorDecorator(_AssessmentEditorDecorator):
    """
    Provides editor link and info on `IQDiscussionAssignment' objects.
    """

    def _predicate(self, context, unused_result):
        return self._is_authenticated \
           and has_permission(ACT_CONTENT_EDIT, context, self.request)

    def _do_decorate_external(self, context, result):
        _links = result.setdefault(LINKS, [])

        result['IsAvailable'] = self._is_available(context)
        result['CanInsertQuestions'] = False

        rels = ['schema', VIEW_DELETE]
        # We provide the edit link no matter the status of the assessment
        # object. Some edits (textual changes) will be allowed no matter what.
        if not self._has_edit_link(_links):
            rels.append('edit')

        if self._can_toggle_is_non_public(context):
            rels.append(VIEW_IS_NON_PUBLIC)

        # chose link context according to the presence of a course
        start_elements = ()
        course = get_course_from_request(self.request)
        link_context = context if course is None else course
        if course is not None:
            start_elements = ('Assessments', context.ntiid)

        # loop through rels and create links
        for rel in rels:
            if rel in self._MARKER_RELS:
                elements = None if not start_elements else start_elements
            else:
                elements = start_elements + ('@@%s' % rel,)
            link = Link(link_context, rel=rel, elements=elements)
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = link_context
            _links.append(link)


@interface.implementer(IExternalMappingDecorator)
class _DiscussionAssignmentResolveTopicDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    Provides `ResolveTopic` links on `IQDiscussionAssignment' objects.
    """

    def _do_decorate_external(self, context, result):
        _links = result.setdefault(LINKS, [])
        start_elements = ()
        course = get_course_from_request(self.request)
        link_context = context if course is None else course
        if course is not None:
            start_elements = ('Assessments', context.ntiid)
        elements = start_elements + ('@@%s' % VIEW_RESOLVE_TOPIC,)
        link = Link(link_context, rel=VIEW_RESOLVE_TOPIC, elements=elements)
        interface.alsoProvides(link, ILocation)
        link.__name__ = ''
        link.__parent__ = link_context
        _links.append(link)


@interface.implementer(IExternalMappingDecorator)
class _PartAutoGradeStatus(Singleton):
    """
    Mark question parts as auto-gradable.
    """

    def decorateExternalMapping(self, context, result):
        result['AutoGradable'] = is_part_auto_gradable(context)


@interface.implementer(IExternalMappingDecorator)
class AssessmentPolicyEditLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    Give editors and instructors policy edit links. This should be available on all
    assignments/inquiries.
    """

    @Lazy
    def request_course(self):
        course = get_course_from_request(self.request)
        return course

    @Lazy
    def is_instructor(self):
        return  self.request_course is not None \
            and is_course_instructor(self.request_course, self.remoteUser)

    def is_editor(self, context):
        return has_permission(ACT_CONTENT_EDIT, context, self.request)

    def get_context(self, context):
        """
        Subclasses can override.
        """
        return context

    def _get_courses(self, context):
        result = _get_course_from_evaluation(context,
                                             user=self.remoteUser,
                                             request=self.request)
        return get_courses(result)

    def _can_edit(self, context):
        """
        Editors or instructors of given course context can edit policy.
        """
        return self.is_editor(context) or self.is_instructor

    def _predicate(self, context, unused_result):
        """
        Course policy edits can only occur on non-global assignments.
        """
        context = self.get_context(context)
        return  self._is_authenticated \
            and not is_global_evaluation(context) \
            and self._can_edit(context)

    def _has_submitted_data(self, context, courses):
        result = has_savepoints(context, courses) \
              or has_submissions(context, courses)
        return result

    def _can_auto_grade(self, context):
        # Content backed assignments can *only* enable auto_grade
        # if the parts are auto-assessable.
        result = True
        if      IQAssignment.providedBy(context) \
            and not IQEditableEvaluation.providedBy(context):
            for part in context.parts or ():
                if part.auto_grade == False:
                    return False
        return result

    def _can_set_time(self, context):
        # Content backed assignments can have time allowed edited
        # if we have a timed assignment.
        result = False
        if     IQEditableEvaluation.providedBy(context) \
            or IQTimedAssignment.providedBy(context):
            if self.is_editor(context):
                result = True
            elif IQTimedAssignment.providedBy(context):
                # Instructors can only change the time allowed if already a
                # timed assignment.
                result = True
        return result

    def _assignment_has_end_date(self, context, course):
        result = False
        if      IQAssignment.providedBy(context) \
            and get_available_for_submission_ending(context, course):
            result = True
        return result

    def _do_decorate_external(self, context, result):
        context = self.get_context(context)
        _links = result.setdefault(LINKS, [])
        courses = self._get_courses(context)
        names = ['date-edit-end', 'date-edit',
                 'max-submissions',
                 'total-points', 'completion-passing-percent']
        # Cannot toggle start date or time allowed if users have started.
        if not self._has_submitted_data(context, courses):
            names.append('date-edit-start')
            if self._can_set_time(context):
                names.append('maximum-time-allowed')
        if self._can_auto_grade(context):
            names.append('auto-grade')

        # set correct context and elements if request comes from a course
        course = self.request_course
        link_context = context if course is None else course
        elements = None if course is None else ('Assessments', context.ntiid)

        if self._assignment_has_end_date(context, course):
            names.append('submission-buffer')

        # loop through name and create links
        for name in names:
            link = Link(link_context, rel=name, elements=elements)
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = link_context
            _links.append(link)


@interface.implementer(IExternalMappingDecorator)
class _AssessmentPracticeLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    Give editors and instructors the practice submission link.
    """

    def _predicate(self, context, unused_result):
        user = self.remoteUser
        course = _get_course_from_evaluation(context,
                                             user,
                                             request=self.request)
        # Legacy, global courses give 'All' perms to course community.
        return self._is_authenticated \
            and not ILegacyCourseInstance.providedBy(course) \
            and (   is_course_instructor_or_editor(course, user)
                 or has_permission(ACT_CONTENT_EDIT, context, self.request))

    def _do_decorate_external(self, context, result):
        _links = result.setdefault(LINKS, [])

        # set correct context and elements if request comes from a course
        course = get_course_from_request(self.request)
        if course is not None:
            link_context = course
            elements = ('Assessments', context.ntiid,
                        '@@' + ASSESSMENT_PRACTICE_SUBMISSION)
        else:
            link_context = context
            elements = ('@@' + ASSESSMENT_PRACTICE_SUBMISSION,)

        link = Link(link_context, rel=ASSESSMENT_PRACTICE_SUBMISSION,
                    elements=elements)
        interface.alsoProvides(link, ILocation)
        link.__name__ = ''
        link.__parent__ = link_context
        _links.append(link)


@component.adapter(IQAssessment)
@interface.implementer(IExternalMappingDecorator)
class _AssessmentLibraryPathLinkDecorator(Singleton):
    """
    Create a `LibraryPath` link to our container id.
    """

    def decorateExternalMapping(self, context, result):
        external_ntiid = to_external_ntiid_oid(context)
        if external_ntiid is not None:
            path = '/dataserver2/%s' % LIBRARY_PATH_GET_VIEW
            link = Link(path, rel=LIBRARY_PATH_GET_VIEW, method='GET',
                        params={'objectId': external_ntiid})
            _links = result.setdefault(LINKS, [])
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = context
            _links.append(link)
