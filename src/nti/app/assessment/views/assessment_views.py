#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment.

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
import six

from itertools import chain
from collections import defaultdict
from collections import OrderedDict

from datetime import datetime

from io import BytesIO

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.cachedescriptors.property import Lazy

from zope.event import notify

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_RESOLVE_TOPIC
from nti.app.assessment import VIEW_UNLOCK_POLICIES
from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.common.evaluations import get_evaluation_courses

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import ICourseAssignmentAttemptMetadata

from nti.app.assessment.views.utils import plain_text
from nti.app.assessment.views.utils import _tx_string
from nti.app.assessment.views.utils import _display_list
from nti.app.assessment.views.utils import _handle_non_gradable_connecting_part
from nti.app.assessment.views.utils import _handle_multiple_choice_multiple_answer
from nti.app.assessment.views.utils import _handle_multiple_choice_part
from nti.app.assessment.views.utils import _handle_modeled_content_part
from nti.app.assessment.views.utils import _handle_free_response_part

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentlibrary.utils import PAGE_INFO_MT
from nti.app.contentlibrary.utils import PAGE_INFO_MT_JSON
from nti.app.contentlibrary.utils import find_page_info_view_helper

from nti.app.externalization.error import raise_json_error

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.appserver.interfaces import IDisplayableTimeProvider
from nti.appserver.interfaces import INewObjectTransformer

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPostView

from nti.assessment.common import get_containerId

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQDiscussionAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.assessment.interfaces import IQNonGradableConnectingPart
from nti.assessment.interfaces import IQNonGradableFreeResponsePart
from nti.assessment.interfaces import IQNonGradableMultipleChoicePart
from nti.assessment.interfaces import IQNonGradableModeledContentPart
from nti.assessment.interfaces import IQNonGradableMultipleChoiceMultipleAnswerPart
from nti.assessment.interfaces import IQFillInTheBlankWithWordBankQuestion

from nti.assessment.interfaces import UnlockQAssessmentPolicies

from nti.contentfragments.interfaces import IPlainTextContentFragment

from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.utils import is_course_instructor

from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussion

from nti.contenttypes.courses.discussions.utils import resolve_discussion_course_bundle

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import ICourseOutlineContentNode
from nti.contenttypes.courses.interfaces import ICourseSelfAssessmentItemCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.courses.legacy_catalog import ILegacyCourseInstance

from nti.contenttypes.courses.utils import get_parent_course

from nti.contenttypes.presentation.interfaces import INTIAssignmentRef
from nti.contenttypes.presentation.interfaces import INTIQuestionSetRef
from nti.contenttypes.presentation.interfaces import INTILessonOverview

from nti.dataserver import authorization as nauth

from nti.dataserver.contenttypes.forums.interfaces import ITopic

from nti.dataserver.users.users import User

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.proxy import removeAllProxies

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.site import get_component_hierarchy_names

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED

# In pyramid 1.4, there is some minor wonkiness with the accept= request predicate.
# Your view can get called even if no Accept header is present if all the defined
# views include a non-matching accept predicate. Still, this is much better than
# the behaviour under 1.3.

_read_view_defaults = dict(route_name='objects.generic.traversal',
                           renderer='rest',
                           permission=nauth.ACT_READ,
                           request_method='GET')
_question_view = dict(context=IQuestion)
_question_view.update(_read_view_defaults)

_question_set_view = dict(context=IQuestionSet)
_question_set_view.update(_read_view_defaults)

_assignment_view = dict(context=IQAssignment)
_assignment_view.update(_read_view_defaults)

_inquiry_view = dict(context=IQInquiry)
_inquiry_view.update(_read_view_defaults)


@view_config(accept=str(PAGE_INFO_MT_JSON),
             **_question_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
             **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
             **_assignment_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
             **_inquiry_view)
@view_config(accept=str(PAGE_INFO_MT),
             **_question_view)
@view_config(accept=str(PAGE_INFO_MT),
             **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT),
             **_inquiry_view)
@view_config(accept=str(PAGE_INFO_MT),
             **_assignment_view)
def pageinfo_from_question_view(request):
    assert request.accept
    # questions are now generally held within their containing IContentUnit,
    # but some old tests don't parent them correctly, using strings
    content_unit_or_ntiid = request.context.__parent__
    return find_page_info_view_helper(request, content_unit_or_ntiid)


@view_config(accept='application/vnd.nextthought.link+json',
             **_question_view)
@view_config(accept='application/vnd.nextthought.link+json',
             **_question_set_view)
@view_config(accept='application/vnd.nextthought.link+json',
             **_assignment_view)
@view_config(accept='application/vnd.nextthought.link+json',
             **_inquiry_view)
def get_question_view_link(unused_request):
    # Not supported.
    return hexc.HTTPBadRequest()


del _inquiry_view
del _question_view
del _assignment_view
del _read_view_defaults


class AssignmentsByOutlineNodeMixin(AbstractAuthenticatedView):

    _LEGACY_UAS = (
        "NTIFoundation DataLoader NextThought/1.0",
        "NTIFoundation DataLoader NextThought/1.1.",
        "NTIFoundation DataLoader NextThought/1.2.",
        "NTIFoundation DataLoader NextThought/1.3.",
        "NTIFoundation DataLoader NextThought/1.4.0"
    )

    @Lazy
    def _is_editor(self):
        instance = ICourseInstance(self.context)
        return has_permission(nauth.ACT_CONTENT_EDIT, instance)

    @Lazy
    def is_ipad_legacy(self):
        result = False
        ua = self.request.environ.get('HTTP_USER_AGENT', '')
        if ua:
            for bua in self._LEGACY_UAS:
                if ua.startswith(bua):
                    result = True
                    break
        return result

    @Lazy
    def _lastModified(self):
        instance = ICourseInstance(self.context)
        result = IQEvaluations(instance).lastModified or 0
        for package in get_course_packages(instance):
            lastMod = IQAssessmentItemContainer(package).lastModified
            result = max(result, lastMod or 0)
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               request_method='GET',
               name='AssignmentsByOutlineNode')  # See decorators
class AssignmentsByOutlineNodeView(AssignmentsByOutlineNodeMixin):
    """
    For course instances (and things that can be adapted to them),
    there is a view at ``/.../AssignmentsByOutlineNode``. For
    authenticated users, it returns a map from NTIID to the assignments
    contained within that NTIID.

    At this time, nodes in the course outline
    do not have their own identity as NTIIDs; therefore, the NTIIDs
    returned from here are the NTIIDs of content pages that show up
    in the individual lessons; for maximum granularity, these are returned
    at the lowest level, so a client may need to walk \"up\" the tree
    to identify the corresponding level it wishes to display.
    """

    def _get_course_ntiids(self, instance):
        courses = (instance,)
        parent_course = get_parent_course(instance)
        # We want to check our parent course for refs
        # in the outline, if we have shared outlines.
        if      parent_course != instance \
            and instance.Outline == parent_course.Outline:
            courses = (instance, parent_course)
        return {ICourseCatalogEntry(x).ntiid for x in courses}

    def _do_legacy_outline(self, instance, items, outline, reverse_qset):
        """
        Build the outline dict for legacy courses by iterating through
        the outline nodes.
        """
        def _recur(node):
            if ICourseOutlineContentNode.providedBy(node) and node.ContentNTIID:
                key = node.ContentNTIID
                node_results = []
                # Check children content units
                content_unit = find_object_with_ntiid(key)
                if content_unit is not None:
                    for content in chain((content_unit,), content_unit.children or ()):
                        assgs = items.get(content.ntiid)
                        if assgs:
                            node_results.extend(x.ntiid for x in assgs)
                name = node.LessonOverviewNTIID
                lesson = component.queryUtility(INTILessonOverview,
                                                name=name or '')
                for group in lesson or ():
                    for item in group or ():
                        if INTIAssignmentRef.providedBy(item):
                            node_results.append(item.target or item.ntiid)
                        elif INTIQuestionSetRef.providedBy(item):
                            ntiid = reverse_qset.get(item.target)
                            if ntiid:
                                node_results.append(ntiid)
                if node_results:
                    outline[key] = node_results
            for child in node.values():
                _recur(child)
        _recur(instance.Outline)
        return outline

    def _do_outline(self, instance, items, outline, reverse_qset):
        """
        Build the outline dict by fetching all assignment refs in our catalog.
        """
        # use library catalog to find
        # all assignment and question-set refs
        seen = set()
        catalog = get_library_catalog()
        sites = get_component_hierarchy_names()
        course_ntiids = self._get_course_ntiids(instance)
        provided = (INTIAssignmentRef, INTIQuestionSetRef)
        for obj in catalog.search_objects(provided=provided,
                                          container_ntiids=course_ntiids,
                                          sites=sites,
                                          container_all_of=False):
            # find property content node
            node = find_interface(obj, ICourseOutlineContentNode, strict=False)
            if node is None or not node.ContentNTIID:
                continue
            key = node.ContentNTIID

            # start if possible with collected items
            assgs = items.get(key)
            if assgs and key not in seen:
                seen.add(key)
                outline[key] = [x.ntiid for x in assgs]

            # add target to outline key
            if INTIAssignmentRef.providedBy(obj):
                outline.setdefault(key, [])
                outline[key].append(obj.target or obj.ntiid)
            elif INTIQuestionSetRef.providedBy(obj):
                ntiid = reverse_qset.get(obj.target)
                if ntiid:
                    outline.setdefault(key, [])
                    outline[key].append(ntiid)

        return outline

    def _build_outline(self, instance, items, outline):
        # reverse question set map
        # this is done in case question set refs
        # appear in a lesson overview
        reverse_qset = {}
        for assgs in items.values():
            for asg in assgs:
                for part in asg.parts or ():
                    reverse_qset[part.question_set.ntiid] = asg.ntiid

        if ILegacyCourseInstance.providedBy(instance):
            result = self._do_legacy_outline(instance,
                                             items,
                                             outline,
                                             reverse_qset)
        else:
            result = self._do_outline(instance, items, outline, reverse_qset)
        return result

    def _external_object(self, obj):
        return obj

    def _build_catalog(self, instance, result):
        catalog = ICourseAssignmentCatalog(instance)
        uber_filter = get_course_assessment_predicate_for_user(self.remoteUser,
                                                               instance)
        # Must grab all assigments in our parent (since they may be referenced
        # in shared lessons.
        assignments = catalog.iter_assignments(course_lineage=True)
        for asg in (x for x in assignments if self._is_editor or uber_filter(x)):
            container_id = get_containerId(asg)
            if container_id:
                result.setdefault(container_id, []).append(asg)
            else:
                logger.error("%s is an assignment without parent container",
                             asg.ntiid)
        return result

    def __call__(self):
        result = LocatedExternalDict()
        result.__name__ = self.request.view_name
        result.__parent__ = self.request.context

        instance = ICourseInstance(self.request.context)
        result[LAST_MODIFIED] = result.lastModified = self._lastModified

        if self.is_ipad_legacy:
            self._build_catalog(instance, result)
        else:
            items = {}
            outline = result['Outline'] = {}
            self._build_catalog(instance, items)
            self._build_outline(instance, items, outline)
            result[ITEMS] = final_items = {}
            for key, vals in items.items():
                final_items[key] = [self._external_object(x) for x in vals]
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               request_method='GET',
               name='AssignmentSummaryByOutlineNode')  # See decorators
class AssignmentSummaryByOutlineNodeView(AssignmentsByOutlineNodeView):
    """
    A `AssigmentsByOutlineNodeView` that only returns summaries of
    assessment objects.
    """

    def _external_object(self, obj):
        return to_external_object(obj, name="summary")


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               request_method='GET',
               name='NonAssignmentAssessmentItemsByOutlineNode')  # See decorators
class NonAssignmentsByOutlineNodeView(AssignmentsByOutlineNodeMixin):
    """
    For course instances (and things that can be adapted to them),
    there is a view at ``/.../NonAssignmentAssessmentItemsByOutlineNode``. For
    authenticated users, it returns a map from NTIID to the assessment items
    contained within that NTIID.

    At the time this was created, nodes in the course outline
    do not have their own identity as NTIIDs; therefore, the NTIIDs
    returned from here are the NTIIDs of content pages that show up
    in the individual lessons; for maximum granularity, these are returned
    at the lowest level, so a client may need to walk \"up\" the tree
    to identify the corresponding level it wishes to display.
    """

    def _external_object(self, obj):
        return obj

    def _do_catalog(self, instance, result):
        qsids_to_strip = set()
        data = defaultdict(dict)
        catalog = ICourseSelfAssessmentItemCatalog(instance)
        for item in catalog.iter_assessment_items(exclude_editable=False):
            # CS: We can remove proxies since the items are neither assignments
            # nor survey, so no course lookup is necesary
            item = removeAllProxies(item)
            container_id = get_containerId(item)
            if container_id:
                data[container_id][item.ntiid] = item
            else:
                logger.error("%s is an item without container", item.ntiid)

        # Now remove the forbidden
        for ntiid, items in data.items():
            result_items = (items[x]
                            for x in items.keys() if x not in qsids_to_strip)
            if not self.is_ipad_legacy:
                result_items = (self._external_object(x) for x in result_items)
            if result_items:
                result[ntiid] = tuple(result_items)
        return result

    def __call__(self):
        result = LocatedExternalDict()
        result.__name__ = self.request.view_name
        result.__parent__ = self.request.context

        instance = ICourseInstance(self.request.context)
        result[LAST_MODIFIED] = result.lastModified = self._lastModified

        if self.is_ipad_legacy:
            self._do_catalog(instance, result)
        else:
            items = result[ITEMS] = {}
            self._do_catalog(instance, items)
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_READ,
               request_method='GET',
               name='NonAssignmentAssessmentSummaryItemsByOutlineNode')  # See decorators
class NonAssignmentSummaryByOutlineNodeView(NonAssignmentsByOutlineNodeView):
    """
    A `NonAssignmentsByOutlineNodeView` that only returns summaries of
    assessment objects.
    """

    def _external_object(self, obj):
        return to_external_object(obj, name="summary")


@view_config(route_name="objects.generic.traversal",
             context=IQuestionSet,
             renderer='rest',
             name=ASSESSMENT_PRACTICE_SUBMISSION,
             request_method='POST')
class SelfAssessmentPracticeSubmissionPostView(UGDPostView):
    """
    A practice self-assessment submission view that will assess results
    but not persist.
    """

    def _assess(self, submission):
        transformer = component.queryMultiAdapter((self.request, submission),
                                                  INewObjectTransformer)
        if transformer is None:
            transformer = component.queryAdapter(submission,
                                                 INewObjectTransformer)

        assessed = transformer(submission)
        return assessed

    def _do_call(self):
        submission, unused = self.readCreateUpdateContentObject(self.remoteUser,
                                                                search_owner=True)
        try:
            return self._assess(submission)
        finally:
            self.request.environ['nti.commit_veto'] = 'abort'


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             context=IQAssessment,
             permission=nauth.ACT_READ,
             request_method='GET',
             name="schema")
class AssessmentSchemaView(AbstractAuthenticatedView):

    def __call__(self):
        result = self.context.schema()
        return result


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             context=IQAssignment,
             permission=nauth.ACT_CONTENT_EDIT,
             request_method='POST',
             name=VIEW_UNLOCK_POLICIES)
class UnlockAssignmenPoliciesView(AbstractAuthenticatedView):

    def __call__(self):
        context = self.context
        courses = get_course_from_request(self.request)
        if not courses:
            courses = get_evaluation_courses(context)
        else:
            courses = (courses,)
        notify(UnlockQAssessmentPolicies(context, courses))
        return hexc.HTTPNoContent()


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             context=IQDiscussionAssignment,
             permission=nauth.ACT_READ,
             request_method='GET',
             name=VIEW_RESOLVE_TOPIC)
class DiscussionAssignmentResolveTopicView(AbstractAuthenticatedView):
    """
    For a IQDiscussionAssignment, resolve it into the discussion it is
    pointing to; if given a `user`, return the relevant topic for that
    user.
    """

    def _get_user(self):
        params = CaseInsensitiveDict(self.request.params)
        username = params.get('user') or params.get('username')
        if username:
            user = User.get_user(username)
            if user is None:
                raise_json_error(self.request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                     'message': _(u"User not found."),
                                 },
                                 None)
        else:
            user = self.remoteUser
        return user

    def __call__(self):
        result = None
        user = self._get_user()
        context = find_object_with_ntiid(self.context.discussion_ntiid)
        if ITopic.providedBy(context):
            result = context
        elif ICourseDiscussion.providedBy(context):
            course = ICourseInstance(context, None)
            resolved = resolve_discussion_course_bundle(user=user,
                                                        item=context,
                                                        context=course)
            if resolved is not None:
                cdiss, topic = resolved
                logger.debug('%s resolved to %s', self.context.id, cdiss)
                result = topic

        if result is None:
            logger.warn('No discussion found for discussion assignment (%s) (%s) (%s)',
                        user,
                        self.context.discussion_ntiid,
                        type(context))
            raise_json_error(self.request,
                             hexc.HTTPNotFound,
                             {
                                 'message': _(u"No topic found for assessment."),
                             },
                             None)
        return result


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             name='AssignmentSubmissionsReport.csv',
             renderer='rest',
             permission=nauth.ACT_READ,
             request_method='GET')
class AssignmentSubmissionsReportCSV(AbstractAuthenticatedView):

    @Lazy
    def timezone_util(self):
        return component.queryMultiAdapter((self.remoteUser, self.request),
                                           IDisplayableTimeProvider)

    def _adjust_timestamp(self, timestamp=None):
        if timestamp is None:
            return ''
        date = datetime.utcfromtimestamp(timestamp)
        return self.timezone_util.adjust_date(date)

    @Lazy
    def course(self):
        return ICourseInstance(self.context)

    @Lazy
    def question_functions(self):
        # we only return response for questions below:
        #     Single/Multiple choices,
        #     essay: IQNonGradableModeledContentPart
        #     short answer: IQNonGradableFreeResponsePart
        return [
            (IQNonGradableMultipleChoiceMultipleAnswerPart, _handle_multiple_choice_multiple_answer),
            (IQNonGradableMultipleChoicePart, _handle_multiple_choice_part),
            (IQNonGradableModeledContentPart, _handle_modeled_content_part),
            (IQNonGradableFreeResponsePart, _handle_free_response_part)
        ]

    def _get_function_for_question_type(self, question_part):
        # look through mapping to find a match
        for iface, factory in self.question_functions:
            if iface.providedBy(question_part):
                return factory
        # return None if we can't find a match for this question type.
        return None

    def _check_permission(self):
        # only instructors or admins should be able to view this.
        if not (is_course_instructor(self.course, self.remoteUser)
                or has_permission(nauth.ACT_NTI_ADMIN, self.course, self.request)):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot access to assignment submissions report.")
                             },
                             None)

    def _get_header_row(self, question_order):
        header_row = ['user', 'submission date (%s)' % self.timezone_util.get_timezone_display_name()]

        number_of_assignment_parts = len(self.context.parts)

        for part in self.context.parts or ():
            prefix = plain_text(part.content) if number_of_assignment_parts > 1 else None
            for question in part.question_set.questions:
                # we won't show bank question at this point.
                if IQFillInTheBlankWithWordBankQuestion.providedBy(question):
                    continue

                if len(question.parts) > 1:
                    # If the question has more than one part, we need to
                    # create a column for each part of the question.
                    for part in question.parts:
                        col = plain_text(question.content) + ": " + plain_text(part.content)
                        header_row.append("{}: {}".format(prefix, col) if prefix else col)
                else:
                    content = plain_text(question.content)
                    part_content = plain_text(question.parts[0].content) if question.parts else ''
                    if content and part_content:
                        content = '%s: %s' % (content, part_content)
                    elif part_content:
                        content = part_content
                    header_row.append("{}: {}".format(prefix, content) if prefix else content)
                question_order[question.ntiid] = question
        return header_row

    def __call__(self):
        self._check_permission()

        stream = BytesIO()
        csv_writer = csv.writer(stream)

        question_order = OrderedDict()
        header_row = self._get_header_row(question_order)

        # write header row
        csv_writer.writerow(header_row)

        column_count = len(header_row)

        course = ICourseInstance(self.context)
        metadata = ICourseAssignmentAttemptMetadata(course)

        # Each row contains an assignment submission attempt
        # submitted by a user to this assignment.
        user_rows = []
        for username, item in metadata.items():
            attempts = item.get(self.context.id)
            if not attempts:
                continue

            for attempt in attempts.values():
                submission = attempt.HistoryItem.Submission
                if submission is None:
                    continue

                row = [username, self._adjust_timestamp(submission.createdTime)]
                for qset_submission in submission.parts or ():

                    user_question_to_results = {}

                    for question_submission in qset_submission.questions or ():
                        question = component.queryUtility(IQuestion, name=question_submission.questionId)
                        # we won't show bank question at this point.
                        if IQFillInTheBlankWithWordBankQuestion.providedBy(question):
                            continue

                        user_question_results = []
                        for part_idx, part in enumerate(zip(question_submission.parts, question.parts)):
                            question_part_submission, question_part = part

                            result = ''
                            if question_part_submission is None:
                                # user may not respond to a question part.
                                user_question_results.append(result)
                                continue

                            question_handler = self._get_function_for_question_type(question_part)
                            if question_handler is not None:
                                result = question_handler(question_part_submission,
                                                          question,
                                                          part_idx)
                            user_question_results.append(result)

                        if user_question_results:
                            assert len(user_question_results) == len(question.parts)
                            user_question_to_results[question.ntiid] = user_question_results

                    # Now build our user row via the question order
                    for question_ntiid, question in question_order.items():
                        user_result = user_question_to_results.get(question_ntiid)
                        if user_result is None:
                            for unused_idx in question.parts or ():
                                row.append(',')
                        else:
                            row.extend(user_result)

                assert len(row) == column_count
                user_rows.append(row)

        for row in user_rows:
            csv_writer.writerow(row)

        stream.flush()
        stream.seek(0)
        # pylint: disable=no-member
        filename = self.context.title or self.context.id
        filename = filename + "_assignment_submissions_report.csv"
        self.request.response.body_file = stream
        self.request.response.content_type = 'text/csv; charset=UTF-8'
        self.request.response.content_disposition = 'attachment; filename="%s"' % filename
        return self.request.response
