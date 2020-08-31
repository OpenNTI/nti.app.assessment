#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import copy
import uuid
import itertools
from datetime import datetime
from collections import Mapping

from zope import interface
from zope import lifecycleevent

from zope.cachedescriptors.property import Lazy

from zope.event import notify as event_notify

from zope.i18n import translate

from zope.interface.common.idatetime import IDateTime

from zope.schema.interfaces import InvalidValue

from pyramid import httpexceptions as hexc

from nti.app.assessment.common.evaluations import get_evaluation_courses
from nti.app.assessment.common.evaluations import is_assignment_non_public_only
from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.common.grading import regrade_evaluation

from nti.app.assessment.common.policy import validate_auto_grade
from nti.app.assessment.common.policy import get_auto_grade_policy
from nti.app.assessment.common.policy import validate_auto_grade_points

from nti.app.assessment.common.utils import get_courses
from nti.app.assessment.common.utils import make_evaluation_ntiid
from nti.app.assessment.common.utils import get_available_for_submission_ending
from nti.app.assessment.common.utils import get_available_for_submission_beginning

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import import_evaluation_content
from nti.app.assessment.evaluations.utils import validate_structural_edits
from nti.app.assessment.evaluations.utils import re_register_assessment_object

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import get_package_from_request

from nti.app.assessment.views import MessageFactory as _

from nti.app.externalization.error import raise_json_error

from nti.appserver.ugd_edit_views import UGDPutView

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQDiscussionAssignment
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import QAssessmentPoliciesModified
from nti.assessment.interfaces import QAssessmentDateContextModified

from nti.common.string import is_true
from nti.common.string import is_false

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussion

from nti.contenttypes.courses.interfaces import SUPPORTED_DATE_KEYS

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSubInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import get_courses_for_packages

from nti.dataserver.contenttypes.forums.interfaces import ITopic

from nti.externalization.externalization import to_external_object

from nti.externalization.internalization import notifyModified

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import StandardInternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.links.links import Link

from nti.recorder.utils import record_transaction

from nti.traversal.traversal import find_interface

CLASS = StandardExternalFields.CLASS
ITEMS = StandardExternalFields.ITEMS
LINKS = StandardExternalFields.LINKS
NTIID = StandardExternalFields.NTIID
MIME_TYPE = StandardExternalFields.MIMETYPE

INTERNAL_NTIID = StandardInternalFields.NTIID

VERSION = u'Version'


def get_courses_from_assesment(assesment):
    course = find_interface(assesment, ICourseInstance, strict=False)
    if course is not None:
        result = (course,)
    else:
        package = find_interface(assesment, IContentPackage, strict=False)
        if package is None:
            result = ()
        else:
            result = get_courses_for_packages(packages=package.ntiid)
    return result


class AssessmentPutView(UGDPutView):

    CONFIRM_CODE = 'AssessmentDateConfirm'
    TO_AVAILABLE_CODE = 'UnAvailableToAvailable'
    TO_UNAVAILABLE_CODE = 'AvailableToUnavailable'

    TO_AVAILABLE_MSG = None
    TO_UNAVAILABLE_MSG = None
    DUE_DATE_CONFIRM_MSG = _(u'Are you sure you want to change the due date?')

    NON_DATE_POLICY_KEYS = ("auto_grade", 'total_points',
                            'maximum_time_allowed', 'submission_buffer',
                            'max_submissions', 'submission_priority',
                            'completion_passing_percent')

    def readInput(self, value=None):
        result = UGDPutView.readInput(self, value=value)
        [result.pop(x, None) for x in (NTIID, INTERNAL_NTIID)]
        return result

    def _raise_conflict_error(self, code, message, course, ntiid, force_flag_name='force'):
        entry = ICourseCatalogEntry(course)
        logger.info('Attempting to change assignment (%s) (%s) (%s)',
                    code,
                    ntiid,
                    entry.ntiid)
        params = dict(self.request.params)
        params[force_flag_name] = True
        links = (
            Link(self.request.path, rel='confirm',
                 params=params, method='PUT'),
        )
        raise_json_error(self.request,
                         hexc.HTTPConflict,
                         {
                             CLASS: 'DestructiveChallenge',
                             'message': message,
                             'code': code,
                             LINKS: to_external_object(links),
                             MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
                         },
                         None)

    @classmethod
    def _is_date_in_range(cls, start_date, end_date, now):
        """
        Returns if we are currently within a possibly open-ended date range.
        """
        # Must have at least one date to be considered in-range.
        result = (not start_date or start_date < now) \
             and (not end_date or now < end_date)
        return bool(result)

    @classmethod
    def _start_date_available_change(cls, old_start_date, new_start_date, now):
        """
        Returns if the start date changes availability.
        """
        # 1. Move start date in future (old start date non-None)
        # 2. Move start date in past (new start date non-None)
        return old_start_date != new_start_date \
            and  (
                   (new_start_date
                    and cls._is_date_in_range(old_start_date, new_start_date, now))
                 or
                   (old_start_date
                    and cls._is_date_in_range(new_start_date, old_start_date, now)))

    def _get_date_object(self, new_date, default, field):
        result = default
        try:
            if new_date and new_date is not default:
                result = IDateTime(new_date)
        except (ValueError, InvalidValue):
            # Now that all dates go into policy, we raise here.
            self._raise_error('InvalidType',
                              _(u'Assessment date is invalid.'),
                              field=field)
        return result

    def validate_date_boundaries(self, contentObject, externalValue, courses=()):
        """
        Validates that the assessment does not change availability states. If
        so, we throw a 409 with an available `confirm` link for user overrides.
        This only raises a 409 if the date range changes.

        The webapp first publishes the assignment and passes in the availability
        dates if scheduled. If no dates are passed in (and the assignment is
        published), it is considered available.
        """
        _marker = object()
        new_end_date = externalValue.get('available_for_submission_ending',
                                         _marker)
        new_start_date = externalValue.get('available_for_submission_beginning',
                                           _marker)
        if     (new_start_date == None and new_end_date == None) \
            or (new_start_date == _marker and new_end_date == _marker):
            # Both incoming dates empty generally means they are explicitly
            # publishing or drafting; so we do not want to warn about anything.
            return

        now = datetime.utcnow()
        new_start_date = self._get_date_object(new_start_date, _marker,
                                               'available_for_submission_beginning')
        new_end_date = self._get_date_object(new_end_date, _marker,
                                             'available_for_submission_ending')

        for course in courses or ():
            old_end_date = get_available_for_submission_ending(contentObject,
                                                               course)

            old_start_date = get_available_for_submission_beginning(contentObject,
                                                                    course)

            # Use old dates if the dates are not being edited.
            start_date_to_check = old_start_date if new_start_date is _marker else new_start_date
            end_date_to_check = old_end_date if new_end_date is _marker else new_end_date

            # If we're going to/from empty state (undefined), skip.
            if     (not old_end_date and not old_start_date) \
                or (not end_date_to_check and not start_date_to_check):
                continue

            start_date_available_change = self._start_date_available_change(old_start_date,
                                                                            start_date_to_check, now)
            # It's available if published and its dates are in range.
            old_available = contentObject.isPublished() \
                        and self._is_date_in_range(old_start_date,
                                                   old_end_date, now)
            new_available = contentObject.isPublished() \
                        and self._is_date_in_range(start_date_to_check,
                                                   end_date_to_check, now)

            # Note: we allow state to move from closed in past to
            # closed but will reopen in the future unchecked (edge case).
            if old_available and not new_available and start_date_available_change:
                # Start date made unavailable
                self._raise_conflict_error(self.TO_UNAVAILABLE_CODE,
                                           self.TO_UNAVAILABLE_MSG,
                                           course,
                                           contentObject.ntiid)
            elif not old_available and new_available and start_date_available_change:
                # Start date made available
                self._raise_conflict_error(self.TO_AVAILABLE_CODE,
                                           self.TO_AVAILABLE_MSG,
                                           course,
                                           contentObject.ntiid)
            elif old_available != new_available:
                # State change but not due to the start date. Give a
                # due date confirmation message.
                self._raise_conflict_error(self.CONFIRM_CODE,
                                           self.DUE_DATE_CONFIRM_MSG,
                                           course,
                                           contentObject.ntiid)

    def preflight(self, contentObject, externalValue, courses=()):
        if     'available_for_submission_ending' in externalValue \
            or 'available_for_submission_beginning' in externalValue:
            if not self.request.params.get('force', False):
                # We do this during pre-flight because we want to compare our old
                # state versus the new.
                self.validate_date_boundaries(contentObject,
                                              externalValue,
                                              courses=courses)
            # Update our publish modification time since dates may be
            # changing...
            contentObject.update_publish_last_mod()

    def validate(self, contentObject, externalValue, courses=()):
        # We could validate edits based on the unused submission/savepoint
        # code above, based on the input keys being changed.
        for course in courses or ():
            # Validate dates
            end_date = get_available_for_submission_ending(contentObject,
                                                           course)
            start_date = get_available_for_submission_beginning(contentObject,
                                                                course)
            if start_date and end_date and end_date < start_date:
                self._raise_error('AssessmentDueDateBeforeStartDate',
                                  _(u'Due date cannot come before start date.'))
            # Validate auto_grade
            validate_auto_grade(contentObject, course, self.request)
            validate_auto_grade_points(contentObject, course,
                                       self.request, externalValue)

    @property
    def policy_keys(self):
        return SUPPORTED_DATE_KEYS + self.NON_DATE_POLICY_KEYS

    def _do_update_policy(self, course, ntiid, key, value, part=None):
        policies = IQAssessmentPolicies(course)
        if part:
            # Mapping
            part_value = policies.get(ntiid, part, {})
            if not part_value:
                part_value = {}
                if part == 'auto_grade':
                    # Creating a new auto_grade policy part; default to off.
                    part_value['disable'] = True
            part_value[key] = value
            value = part_value
            key = part
        policies.set(ntiid, key, value)

    def _raise_error(self, code, message, field=None):
        """
        Raise a 422 with the give code, message and field (optional).
        """
        data = {
            'code': code,
            'message': message,
        }
        if field:
            data['field'] = field
        raise_json_error(self.request,
                         hexc.HTTPUnprocessableEntity,
                         data,
                         None)

    def _get_value(self, value_type, value, field):
        """
        Get the value for the given type.
        """
        if value_type == bool:
            result = value
            if isinstance(value, six.string_types):
                result = is_true(value)
                if not result and is_false(value):
                    result = False
                elif not result:
                    result = None
            if not isinstance(result, bool):
                self._raise_error('InvalidType',
                                  _(u'Value is invalid.'),
                                  field=field)
        elif value_type in (int, float):
            if value is None:
                # Empty/None is acceptable.
                return None
            try:
                result = value_type(value)
            except (TypeError, ValueError):
                self._raise_error('InvalidType',
                                  _(u'Value is invalid.'),
                                  field=field)
        else:
            raise TypeError()
        return result

    def update_policy(self, courses, ntiid, obj, key, value):
        if key in SUPPORTED_DATE_KEYS:
            if value and not isinstance(value, datetime):
                value = IDateTime(value)
            for course in courses or ():
                dates = IQAssessmentDateContext(course)
                dates.set(ntiid, key, value)
                event_notify(QAssessmentDateContextModified(dates, ntiid, key))
            return

        part = None
        notify_key = key
        notify_value = value
        # TODO: Can we run this through policy validator?
        if key == 'auto_grade':
            # If auto_grade set to 'false', set 'disable' to true in auto_grade
            # section.
            notify_value = value = self._get_value(bool, value, key)
            part = 'auto_grade'
            value = not value
            key = 'disable'
        elif key == 'total_points':
            notify_value = value = self._get_value(float, value, key)
            part = 'auto_grade'
            if value is not None and value <= 0:
                self._raise_error('InvalidValue',
                                  _(u'total_points must be between 0 and 1.'),
                                  field='total_points')
        elif key == 'maximum_time_allowed':
            value = notify_value = self._get_value(int, value, key)
            # If still a timed assignment, we must stay above 60s.
            if      IQTimedAssignment.providedBy(obj) \
                and (not value or value < 60):
                self._raise_error('InvalidValue',
                                  _(u'Time allowed must be at least 60 seconds.'),
                                  field='maximum_time_allowed')
        elif key == 'max_submissions':
            value = notify_value = self._get_value(int, value, key)
            # -1 is unlimited
            if value < 1 and value != -1:
                self._raise_error('InvalidValue',
                                  _(u'Max submissions must be at least 1.'),
                                  field='max_submissions')
        elif key == 'submission_priority':
            value = notify_value = value.lower()
            if value not in ('most_recent', 'highest_grade'):
                self._raise_error('InvalidValue',
                                  _(u'Invalid submission_priority in policy'),
                                  field='submission_priority')
        elif key == 'completion_passing_percent':
            value = notify_value = self._get_value(float, value, key)
            if value is not None and (value <= 0 or value > 1):
                self._raise_error('InvalidValue',
                                  _(u'completion_passing_percent must be between 0 and 1.'),
                                  field='completion_passing_percent')

        factory = QAssessmentPoliciesModified
        for course in courses or ():
            self._do_update_policy(course, ntiid, key, value, part)
            event_notify(factory(course, ntiid, notify_key, notify_value))

    def _update_auto_assess(self, contentObject, auto_assess, courses):
        """
        Update the auto_grade (assess) field on parts.
        """
        if auto_assess is not None:
            value = self._get_value(bool, auto_assess, 'auto_assess')
            for part in contentObject.parts or ():
                part.auto_grade = value
            if value:
                # Auto-assess is enabled, go ahead and regrade.
                for course in courses or ():
                    regrade_evaluation(contentObject, course)

    def notify_and_record(self, contentObject, externalValue):
        """
        Broadcast and notify if our object changes; if we only have
        policy changes, just record the changes themselves without
        locking our object.
        """
        non_policy_changes = set(externalValue) - set(self.policy_keys)
        if non_policy_changes:
            # Auto-assess changes should notify.
            notifyModified(contentObject, externalValue)
        else:
            # If only policy changes, we want to record the change and
            # make sure we remain unlocked.
            record_transaction(contentObject,
                               descriptions=externalValue.keys(),
                               ext_value=externalValue,
                               lock=False)

    def updateContentObject(self, contentObject, externalValue, set_id=False,
                            notify=True, pre_hook=None):
        # check context
        context = get_course_from_request(self.request) \
               or get_package_from_request(self.request)
        if context is None and IQEditableEvaluation.providedBy(contentObject):
            context = find_interface(contentObject, ICourseInstance, strict=False) \
                   or find_interface(contentObject, IContentPackage, strict=False)

        if context is None:
            # We want to require a context when editing an assignment,
            # mainly to ensure we update the assignment policies of the correct
            # courses, versus all courses.
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Cannot edit assessment without context."),
                                 'code': 'CannotEditAssessment',
                             },
                             None)

        # XXX: We'll eventually look for a flag that allows us to
        # update all courses in hierarchy.
        if IContentPackage.providedBy(context):
            courses = get_courses_for_packages(packages=context.ntiid)
        else:
            courses = (context,)
        self.preflight(contentObject, externalValue, courses)

        auto_assess = None
        for key in ('auto_assess', 'AutoAssess'):
            assess_val = externalValue.pop(key, None)
            if assess_val is not None:
                auto_assess = assess_val

        # Remove policy keys to avoid updating fields in the actual assessment
        # object.
        backupData = copy.deepcopy(externalValue)
        for key in self.policy_keys:
            externalValue.pop(key, None)

        if externalValue:
            copied = copy.deepcopy(externalValue)
            result = UGDPutView.updateContentObject(self,
                                                    notify=False,
                                                    set_id=set_id,
                                                    pre_hook=pre_hook,
                                                    externalValue=externalValue,
                                                    contentObject=contentObject)
            externalValue = copied
        else:
            result = contentObject
            externalValue = backupData

        if notify:
            self.notify_and_record(contentObject, externalValue)
        self._update_auto_assess(contentObject, auto_assess, courses)

        # update course policy
        ntiid = contentObject.ntiid
        for key in self.policy_keys:
            if key in backupData:
                self.update_policy(courses, ntiid, contentObject,
                                   key, backupData[key])

        # Validate once we have policy updated.
        self.validate(result, backupData, courses)
        return result


class StructuralValidationMixin(object):
    """
    A mixin to validate the structural state of an IQEditableEvaluation object.
    """

    @Lazy
    def composite(self):
        result = find_interface(self.context, ICourseInstance, strict=False)
        if result is None:
            result = find_interface(self.context,
                                    IContentPackage,
                                    strict=False)
        return result

    @Lazy
    def course(self):
        result = self.composite
        if IContentPackage.providedBy(result):
            result = get_course_from_request()
            if result is None:
                courses = get_courses_for_packages(packages=result.ntiid)
                result = courses[0] if courses else None
        return result

    def _check_part_structure(self, context, externalValue):
        """
        Determines whether this question part has structural changes.
        """
        result = False
        ext_part_ntiid = externalValue.get('NTIID',
                                           externalValue.get('ntiid', ''))
        obj_ntiid = getattr(context, 'ntiid', '')
        if ext_part_ntiid and obj_ntiid and obj_ntiid != ext_part_ntiid:
            result = True
        else:
            analyzer = IQPartChangeAnalyzer(context, None)
            if analyzer is not None:
                # XXX: Is this what we want?
                result = not analyzer.allow(externalValue,
                                            check_solutions=False)
        return result

    def _check_question_structure(self, context, externalValue, require_ntiid=False):
        """
        Determines whether this question has structural changes.
        """
        result = False
        if not isinstance(externalValue, Mapping):
            return result
        ext_question_ntiid = externalValue.get('NTIID',
                                               externalValue.get('ntiid', ''))
        parts = context.parts or ()
        ext_parts = externalValue.get('parts')
        if      (require_ntiid or ext_question_ntiid) \
            and context.ntiid != ext_question_ntiid:
            result = True
        elif ext_parts is not None \
                and len(parts) != len(ext_parts):
            result = True
        elif ext_parts is not None:
            for idx, part in enumerate(context.parts or ()):
                ext_part = externalValue.get('parts')[idx]
                result = self._check_part_structure(part, ext_part)
                if result:
                    break
        return result

    def _check_question_set_structure(self, context, externalValue):
        """
        Determines whether this question set has structural changes.
        """
        result = False
        if not isinstance(externalValue, Mapping):
            return result
        questions = context.questions or ()
        ext_questions = externalValue.get('questions')
        ext_question_set_ntiid = externalValue.get('NTIID',
                                                   externalValue.get('ntiid', ''))
        if      ext_questions is not None \
            and len(questions) != len(ext_questions):
            result = True
        elif    ext_question_set_ntiid \
            and context.ntiid != ext_question_set_ntiid:
            result = True
        elif ext_questions is not None:
            for idx, question in enumerate(questions):
                ext_question = ext_questions[idx]
                result = self._check_question_structure(question, ext_question)
                if result:
                    break
        return result

    def _check_survey_structure(self, context, externalValue):
        """
        Determines whether this question set has structural changes.
        """
        result = False
        if not isinstance(externalValue, Mapping):
            return result
        questions = context.questions or ()
        ext_questions = externalValue.get('questions')
        ext_question_set_ntiid = externalValue.get('NTIID',
                                                   externalValue.get('ntiid', ''))
        if      ext_questions is not None \
            and len(questions) != len(ext_questions):
            result = True
        elif    ext_question_set_ntiid \
            and context.ntiid != ext_question_set_ntiid:
            result = True
        elif ext_questions is not None:
            for idx, question in enumerate(questions):
                ext_question = ext_questions[idx]
                result = self._check_question_structure(question,
                                                        ext_question,
                                                        require_ntiid=True)
                if result:
                    break
        return result

    def _check_assignment_part_structure(self, context, externalValue):
        """
        Determines whether this assignment part has structural changes.
        """
        result = False
        ext_part_ntiid = externalValue.get('NTIID',
                                           externalValue.get('ntiid', ''))
        if ext_part_ntiid \
                and context.ntiid != ext_part_ntiid:
            result = True
        else:
            ext_set = externalValue.get('question_set')
            if ext_set is not None:
                result = self._check_question_set_structure(context.question_set,
                                                            ext_set)
        return result

    def _check_assignment_structure(self, context, externalValue):
        """
        Determines whether this assignment has structural changes.
        """
        result = False
        ext_parts = externalValue.get('parts')
        if ext_parts is not None:
            result = len(context.parts or ()) != len(ext_parts)
            if not result:
                for idx, part in enumerate(context.parts or ()):
                    ext_part = externalValue.get('parts')[idx]
                    result = self._check_assignment_part_structure(part, ext_part)
                    if result:
                        break
        return result

    def _check_structural_change(self, context, externalValue):
        """
        For the given evaluation and input, check if 'structural' changes
        are being made.
        """
        # We do not allow part level modifications.
        result = False
        if IQAssignment.providedBy(context):
            result = self._check_assignment_structure(context, externalValue)
        elif IQuestionSet.providedBy(context):
            result = self._check_question_set_structure(context, externalValue)
        elif IQuestion.providedBy(context):
            result = self._check_question_structure(context, externalValue)
        elif IQSurvey.providedBy(context):
            result = self._check_survey_structure(context, externalValue)
        return result

    def _validate_structural_edits(self, context=None):
        """
        Validate we are allowed to change the given context's
        structural state.
        """
        context = context if context is not None else self.context
        # Validate for all possible courses.
        courses = get_courses(self.course)
        for course in courses or ():
            validate_structural_edits(context, course)

    def _pre_flight_validation(self, context, externalValue=None, structural_change=False):
        """
        Validate whether the incoming changes are 'structural' changes that
        require submission validation or a version bump of containing assignments.
        This must be performed before the content object is updated since we are
        comparing states.
        """
        # Only validate editable items.
        if not IQEditableEvaluation.providedBy(context):
            return

        if not structural_change:
            structural_change = self._check_structural_change(context,
                                                              externalValue)
        if structural_change:
            # We have changes, validate and bump version.
            self._validate_structural_edits(context)
            assignments = get_containers_for_evaluation_object(context)
            for assignment in assignments:
                assignment.update_version()


class EvaluationMixin(StructuralValidationMixin):

    @Lazy
    def _extra(self):
        return str(uuid.uuid4().time_low)

    def get_ntiid(self, context):
        if isinstance(context, six.string_types):
            result = context
        else:
            result = getattr(context, 'ntiid', None)
        return result

    def _re_register(self, context, old_iface, new_iface):
        """
        Unregister the context under the given old interface and register
        under the given new interface.
        """
        re_register_assessment_object(context, old_iface, new_iface)

    def store_evaluation(self, obj, composite, user, check_solutions=True):
        """
        Finish initalizing new evaluation object and store persistently.
        """
        provided = iface_of_assessment(obj)
        evaluations = IQEvaluations(composite)
        obj.ntiid = ntiid = make_evaluation_ntiid(provided, extra=self._extra)
        obj.creator = getattr(user, 'username', user)
        lifecycleevent.created(obj)
        try:
            # XXX mark to avoid checking solutions
            if not check_solutions:
                interface.alsoProvides(obj, IQAvoidSolutionCheck)
            # XXX mark as editable before storing so proper validation is done
            interface.alsoProvides(obj, IQEditableEvaluation)
            evaluations[ntiid] = obj  # gain intid
        finally:
            # XXX remove temp interface
            if not check_solutions:
                interface.noLongerProvides(obj, IQAvoidSolutionCheck)
        return obj

    def get_registered_evaluation(self, obj, composite):
        ntiid = self.get_ntiid(obj)
        evaluations = IQEvaluations(composite)
        if ntiid in evaluations:
            obj = evaluations[ntiid]
        else:
            obj = find_object_with_ntiid(ntiid)
        return obj

    def is_new(self, context):
        ntiid = self.get_ntiid(context)
        return not ntiid

    def handle_question(self, theObject, composite, user, check_solutions=True):
        if self.is_new(theObject):
            theObject = self.store_evaluation(theObject, composite, user,
                                              check_solutions)
        else:
            theObject = self.get_registered_evaluation(theObject, composite)
        [p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
        if theObject is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Question does not exists."),
                                 'code': 'QuestionDoesNotExists',
                             },
                             None)
        return theObject

    def handle_poll(self, theObject, composite, user):
        if self.is_new(theObject):
            theObject = self.store_evaluation(theObject, composite, user, False)
        else:
            theObject = self.get_registered_evaluation(theObject, composite)
        [p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
        if theObject is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Poll does not exists."),
                                 'code': 'PollDoesNotExists',
                             },
                             None)
        return theObject

    def handle_question_set(self, theObject, composite, user, check_solutions=True):
        if self.is_new(theObject):
            questions = indexed_iter()
            for question in theObject.questions or ():
                question = self.handle_question(question, composite,
                                                user, check_solutions)
                questions.append(question)
            theObject.questions = questions
            theObject = self.store_evaluation(theObject, composite, user)
        else:
            theObject = self.get_registered_evaluation(theObject, composite)
        if theObject is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"QuestionSet does not exists."),
                                 'code': 'QuestionSetDoesNotExists',
                             },
                             None)

        return theObject

    def handle_survey(self, theObject, composite, user):
        questions = indexed_iter()
        for idx, poll in enumerate(theObject.questions or ()):
            poll = self.handle_poll(poll, composite, user)
            questions.append(poll)
        theObject.questions = questions
        if self.is_new(theObject):
            theObject = self.store_evaluation(theObject, composite, user)
        else:
            theObject = self.get_registered_evaluation(theObject, composite)
        if theObject is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Survey does not exists."),
                                 'code': 'SurveyDoesNotExists',
                             },
                             None)
        return theObject

    def handle_assignment_part(self, part, course, user):
        question_set = self.handle_question_set(part.question_set,
                                                course,
                                                user)
        part.question_set = question_set
        return part

    def handle_assignment(self, theObject, composite, user):
        # Make sure we handle any parts that may have been
        # added to our existing or new assignment.
        parts = indexed_iter()
        for part in theObject.parts or ():
            part = self.handle_assignment_part(part, composite, user)
            parts.append(part)
        theObject.parts = parts
        if self.is_new(theObject):
            theObject = self.store_evaluation(theObject, composite, user)
            [p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
        else:
            theObject = self.get_registered_evaluation(theObject, composite)
        if theObject is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Assignment does not exists."),
                                 'code': 'AssignmentDoesNotExists',
                             },
                             None)
        return theObject

    def handle_discussion_assignment(self, theObject, composite, user):
        """
        Validate discussion assignment is valid, ignoring any parts
        coming in externally.
        """
        assignment = self.handle_assignment(theObject, composite, user)
        if assignment.discussion_ntiid:
            discussion = find_object_with_ntiid(assignment.discussion_ntiid)
            if discussion is None:
                raise_json_error(self.request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                     'message': _(u"Discussion does not exist."),
                                     'code': 'DiscussionDoesNotExist',
                                 },
                                 None)
            if      not ICourseDiscussion.providedBy(discussion) \
                and not ITopic.providedBy(discussion):
                raise_json_error(self.request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                     'message': _(u"Must point to valid discussion."),
                                     'code': 'InvalidDiscussionAssignment',
                                 },
                                 None)
        return theObject

    def handle_evaluation(self, theObject, composite, sources, user):
        if IQuestion.providedBy(theObject):
            result = self.handle_question(theObject, composite, user)
        elif IQPoll.providedBy(theObject):
            result = self.handle_poll(theObject, composite, user)
        elif IQuestionSet.providedBy(theObject):
            result = self.handle_question_set(theObject, composite, user)
        elif IQSurvey.providedBy(theObject):
            result = self.handle_survey(theObject, composite, user)
        elif IQDiscussionAssignment.providedBy(theObject):
            result = self.handle_discussion_assignment(theObject, composite, user)
        elif IQAssignment.providedBy(theObject):
            result = self.handle_assignment(theObject, composite, user)
        else:
            result = theObject
        # composite is the evaluation home
        theObject.__home__ = composite
        # parse content fields and load sources
        import_evaluation_content(result, composite, user, sources)
        # always register
        register_context(result)
        return result

    def _validate_section_course_items(self, container, items, additional_contexts=None):
        """
        Validate the given question set does not have any section level questions
        when the top-level assessment item is in the parent course.
        """
        context_courses = set()
        for context in itertools.chain((container,), additional_contexts or ()):
            context_course = find_interface(context, ICourseInstance, strict=False)
            if context_course is not None:
                context_courses.add(context_course)
        if not context_courses:
            return

        for item in items or ():
            item_course = find_interface(item, ICourseInstance, strict=False)
            if      item_course is not None \
                and ICourseSubInstance.providedBy(item_course) \
                and item_course not in context_courses:
                    # A question that comes from a section course and
                    # that course is not where the qset/assignment were created
                    msg = _(u"Section course question cannot be inserted in parent course assessment item.")
                    raise_json_error(self.request,
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': msg,
                                         'code': 'InsertSectionQuestionInParentAssessment',
                                     },
                                     None)

    def _validate_section_course(self, item):
        """
        Section-level API created items cannot be inserted into parent-level assessment
        items.
        """
        if IQAssignment.providedBy(item):
            for part in item.parts or ():
                if part.question_set is not None:
                    self._validate_section_course_items(part.question_set,
                                                        part.question_set.questions,
                                                        additional_contexts=(item,) )
        elif IQuestionSet.providedBy(item):
            self._validate_section_course_items(item, item.questions)

    def post_update_check(self, contentObject, unused_externalValue):
        self._validate_section_course(contentObject)

    def _get_required_question(self, item):
        """
        Fetch and validate we are given a question object or the ntiid
        of an existing question object.
        """
        question = self.get_registered_evaluation(item, self.composite)
        if not IQuestion.providedBy(question):
            msg = translate(_(u"Question ${ntiid} does not exist.",
                              mapping={'ntiid': item}))
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': msg,
                                 'code': 'QuestionDoesNotExist',
                             },
                             None)
        return question

    def _get_required_question_set(self, item):
        """
        Fetch and validate we are given a question_set object or the ntiid
        of an existing question_set object.
        """
        question_set = self.get_registered_evaluation(item, self.composite)
        if not IQuestionSet.providedBy(question_set):
            msg = translate(_(u"QuestionSet ${ntiid} does not exist.",
                              mapping={'ntiid': item}))
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': msg,
                                 'code': 'QuestionSetDoesNotExist',
                             },
                             None)
        return question_set

    def auto_complete_questionset(self, context, externalValue):
        questions = indexed_iter() if not context.questions else context.questions
        items = externalValue.get(ITEMS)
        for item in items or ():
            question = self._get_required_question(item)
            questions.append(question)
        context.questions = questions

    def auto_complete_survey(self, context, externalValue):
        questions = indexed_iter() if not context.questions else context.questions
        items = externalValue.get(ITEMS)
        for item in items or ():
            poll = self.get_registered_evaluation(item, self.composite)
            if not IQPoll.providedBy(poll):
                msg = translate(_(u"Question ${ntiid} does not exists.",
                                  mapping={'ntiid': item}))
                raise_json_error(self.request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                     'message': msg,
                                     'code': 'QuestionDoesNotExist',
                                 },
                                 None)
            else:
                questions.append(poll)
        context.questions = questions

    def _default_assignment_public_status(self, context):
        """
        For the given assignment, set our default public status based
        on whether or not all courses contained by this assignment
        are non-public.
        """
        if self.course is not None:
            is_non_public = is_assignment_non_public_only(context)
            context.is_non_public = is_non_public

    def auto_complete_assignment(self, context, externalValue):
        # Clients are expected to create parts/qsets as needed.
        parts = indexed_iter() if not context.parts else context.parts
        for part in parts:
            # Assuming one part.
            qset = externalValue.get('question_set')
            if qset:
                part.question_set = self._get_required_question_set(qset)
            if part.question_set is not None:
                self.auto_complete_questionset(part.question_set,
                                               externalValue)
        context.parts = parts
        self._default_assignment_public_status(context)


class ValidateAutoGradeMixin(object):
    """
    A post-update mixin that validates the context (which is in a course lineage)
    can be auto_graded after the given changes. If not, we challenge
    appropriately. If confirmed, we disable auto-grading for this contextual
    assignment.
    """

    def _get_courses(self, context):
        course = find_interface(context, ICourseInstance, strict=False)
        if course is None:
            courses = get_evaluation_courses(context)
        else:
            courses = (course,)
        result = set()
        for course in courses or ():
            result.update(get_courses(course))
        return result

    def _disable_auto_grade(self, assignment, course):
        policy = get_auto_grade_policy(assignment, course)
        policy['disable'] = True
        event_notify(QAssessmentPoliciesModified(course, assignment.ntiid, 'auto_grade', False))

    def _validate_auto_grade(self, params):
        """
        Will validate and raise a challenge if the user wants to disable auto-grading
        and add the non-auto-gradable question to this question set. If overridden,
        we will insert the question and disable auto-grade for all assignments
        referencing this question set.
        """
        # Make sure our auto_grade status still holds.
        courses = self._get_courses(self.context)
        assignments = get_containers_for_evaluation_object(self.context)
        if params:
            override_auto_grade = params.get('overrideAutoGrade')
        else:
            override_auto_grade = False
        is_valid = None
        override_auto_grade = is_true(override_auto_grade)
        for course in courses or ():
            for assignment in assignments or ():
                is_valid = validate_auto_grade(assignment, course, self.request,
                                               challenge=True,
                                               raise_exc=not override_auto_grade,
                                               method=self.request.method)
                if not is_valid and override_auto_grade:
                    self._disable_auto_grade(assignment, course)
