#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

import transaction

import six
import copy

try:
    from collections.abc import Mapping
except ImportError: # Py2
    from collections import Mapping

from Acquisition import aq_base
from requests.structures import CaseInsensitiveDict

from zope import interface
from zope import lifecycleevent

from zope.cachedescriptors.property import Lazy

from zope.event import notify as event_notify

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS

from nti.app.assessment.common.editting import pre_validate_question_change

from nti.app.assessment.common.evaluations import get_max_time_allowed
from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.common.history import delete_inquiry_submissions

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import delete_evaluation

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import RegradeQuestionEvent
from nti.app.assessment.interfaces import IQAvoidSolutionCheck

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views.creation_views import QuestionSetInsertView

from nti.app.assessment.views.view_mixins import VERSION
from nti.app.assessment.views.view_mixins import EvaluationMixin
from nti.app.assessment.views.view_mixins import AssessmentPutView
from nti.app.assessment.views.view_mixins import ValidateAutoGradeMixin

from nti.app.base.abstract_views import get_all_sources

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.internalization import update_object_from_external_object

from nti.app.contentfile import validate_sources

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPutView

from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import TIMED_ASSIGNMENT_MIME_TYPE

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQDiscussionAssignment

from nti.assessment.interfaces import QuestionRemovedFromContainerEvent

from nti.assessment.question import QQuestionSet

from nti.assessment.randomized.interfaces import IQuestionBank

from nti.assessment.randomized.question import QQuestionBank

from nti.common.string import is_true

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import StandardInternalFields

from nti.externalization.internalization import notifyModified

from nti.ntiids.oids import to_external_ntiid_oid

from nti.recorder.record import copy_transaction_history

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)

OID = StandardExternalFields.OID
ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
MIMETYPE = StandardExternalFields.MIMETYPE
ITEM_COUNT = StandardExternalFields.ITEM_COUNT
INTERNAL_NTIID = StandardInternalFields.NTIID


@view_config(route_name='objects.generic.traversal',
             context=IQuestionSet,
             request_method='PUT',
             permission=nauth.ACT_CONTENT_EDIT,
             renderer='rest',
             name=VIEW_QUESTION_SET_CONTENTS)
class QuestionSetReplaceView(QuestionSetInsertView):
    """
    Replaces a question at the given index path.
    """

    def _get_current_question_at_index(self, index):
        if index is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Must give an index to replace a question."),
                                 'code': 'QuestionReplaceIndexRequired',
                             },
                             None)
        try:
            old_question = self.context[index]
        except (KeyError, IndexError):
            old_question = None

        params = CaseInsensitiveDict(self.request.params)
        old_ntiid = params.get('ntiid')
        # If they give us ntiid, validate that against our index.
        if     old_question is None \
            or (old_ntiid and old_ntiid != old_question.ntiid):
            raise_json_error(self.request,
                             hexc.HTTPConflict,
                             {
                                 'message': _(u'The question no longer exists at this index.'),
                                 'code': 'InvalidQuestionReplaceIndex'
                             },
                             None)
        return old_question

    def _do_insert(self, new_question, index):
        old_question = self._get_current_question_at_index(index)
        self.context.remove(old_question)
        factory = QuestionRemovedFromContainerEvent
        event_notify(factory(self.context, old_question, index))
        self.context.insert(index, new_question)
        logger.info('Replaced question (old=%s) (new=%s)',
                    old_question.ntiid, new_question.ntiid)



@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='PUT',
               permission=nauth.ACT_CONTENT_EDIT)
class EvaluationPutView(EvaluationMixin, UGDPutView):

    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the object definition.")

    def readInput(self, value=None):
        result = UGDPutView.readInput(self, value=value)
        for key in (NTIID, VERSION):
            result.pop(key, None)
            result.pop(key.lower(), None)
        return result

    def _check_object_constraints(self, obj, externalValue):
        super(EvaluationPutView, self)._check_object_constraints(obj, externalValue)
        self._pre_flight_validation(obj, externalValue)
        if not IQEditableEvaluation.providedBy(obj):
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': self.OBJ_DEF_CHANGE_MSG,
                                 'code': 'CannotChangeObjectDefinition',
                             },
                             None)

    def _get_post_update_source(self, externalValue):
        return externalValue, copy.deepcopy(externalValue)

    def updateContentObject(self, contentObject, externalValue,
                            set_id=False, notify=True):
        originalSource = copy.deepcopy(externalValue)
        externalValue, update_source = self._get_post_update_source(externalValue)
        result = UGDPutView.updateContentObject(self,
                                                contentObject,
                                                externalValue,
                                                set_id=set_id,
                                                notify=False)
        self.post_update_check(contentObject, update_source)
        sources = get_all_sources(self.request)
        if sources:
            validate_sources(self.remoteUser, result.model, sources)
        self.handle_evaluation(contentObject, self.composite,
                               sources, self.remoteUser)
        # validate changes - subscribers
        notifyModified(contentObject, originalSource)
        return result


@view_config(route_name='objects.generic.traversal',
             context=IQuestion,
             request_method='PUT',
             permission=nauth.ACT_CONTENT_EDIT,
             renderer='rest')
class QuestionPutView(EvaluationPutView, ValidateAutoGradeMixin):

    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the question definition.")

    def _check_object_constraints(self, obj, externalValue):
        super(QuestionPutView, self)._check_object_constraints(obj, externalValue)
        self._pre_flight_validation(obj, externalValue)

    def updateContentObject(self, contentObject, externalValue, **kwargs):
        # We need to check our question part changes before we update our
        # content object.
        part_regrades = pre_validate_question_change(contentObject, externalValue)
        result = super(QuestionPutView, self).updateContentObject(contentObject,
                                                                  externalValue,
                                                                  **kwargs)
        # Only regrade after our content object is updated.
        if part_regrades:
            event_notify(RegradeQuestionEvent(result, part_regrades))
        self._validate_auto_grade(CaseInsensitiveDict(self.request.params))
        return result

    def __call__(self):
        result = super(QuestionPutView, self).__call__()

        # For users with edit access, use an externalizer that emits solutions
        self.request._v_nti_render_externalizable_name = "solutions"

        return result


def _ntiid_only(ext_obj):
    """
    Only contains NTIID and no other keys.
    """
    if not ext_obj:
        return False
    if isinstance(ext_obj, six.string_types):
        return True
    ntiid = ext_obj.get('ntiid') or ext_obj.get(NTIID)
    return ntiid and len(ext_obj) == 1


def _qset_with_ntiids_only(qset_ext):
    """
    Check if our question set *only* has question ntiids.
    """
    questions = qset_ext.get('questions')
    result = questions and all(_ntiid_only(x) for x in questions)
    return result


def _assignment_part_with_question_set_ntiid_only(part_ext):
    """
    Check if our assignment part has *only* an ntiid for the question set.
    """
    qset = part_ext.get('question_set')
    return _ntiid_only(qset)


@view_config(route_name='objects.generic.traversal',
             context=IQuestionSet,
             request_method='PUT',
             permission=nauth.ACT_CONTENT_EDIT,
             renderer='rest')
class QuestionSetPutView(EvaluationPutView):

    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the question set definition.")

    def _check_object_constraints(self, obj, externalValue):
        super(QuestionSetPutView, self)._check_object_constraints(obj, externalValue)
        self._pre_flight_validation(obj, externalValue)

    def post_update_check(self, contentObject, originalSource):
        if IQEditableEvaluation.providedBy(contentObject):
            items = originalSource.get(ITEMS)
            if items:  # list of ntiids
                contentObject.questions = indexed_iter()  # reset
                self.auto_complete_questionset(contentObject, originalSource)
        super(QuestionSetPutView, self).post_update_check(contentObject, originalSource)

    def _get_post_update_source(self, externalValue):
        """
        If our question set just has ntiids, pop from original (in order
        to update without 422ing) and return items for postUpdate.
        """
        result = dict()
        ntiids_only = _qset_with_ntiids_only(externalValue)
        if ntiids_only:
            result[ITEMS] = externalValue.pop('questions')
        return externalValue, result

    def _update_assignments(self, old_obj, new_obj):
        """
        Update all assignments pointing to our question set.
        Any refs in lessons should still work (since we point to ntiid).
        """
        assignments = get_containers_for_evaluation_object(old_obj)
        for assignment in assignments:
            for part in assignment.parts or ():
                if part.question_set.ntiid == old_obj.ntiid:
                    part.question_set = new_obj

    def _copy_question_set(self, source, target):
        """
        Copy fields from one question set to the other, also
        copying transaction history and updating assignment refs.
        """
        target.__home__ = source.__home__
        target.__parent__ = source.__parent__
        for key, val in source.__dict__.items():
            if not key.startswith('_'):
                setattr(target, key, val)
        copy_transaction_history(source, target)
        self._update_assignments(source, target)

    def _create_new_object(self, obj, composite):
        evaluations = IQEvaluations(composite)
        lifecycleevent.created(obj)
        # XXX mark as editable before storing so proper validation is done
        interface.alsoProvides(obj, IQEditableEvaluation)
        evaluations[obj.ntiid] = obj  # gain intid

    def _copy_to_new_type(self, old_obj, new_obj):
        # XXX: Important to get composite here before we mangle context.
        composite = self.composite
        self._copy_question_set(old_obj, new_obj)
        delete_evaluation(old_obj)
        self._create_new_object(new_obj, composite)

    def _transform_to_bank(self, contentObject):
        """
        Transform from a question set to a question bank.
        """
        self._pre_flight_validation(contentObject, structural_change=True)
        result = QQuestionBank()
        self._copy_to_new_type(contentObject, result)
        self._re_register(result, IQuestionSet, IQuestionBank)
        return result

    def _transform_to_non_bank(self, contentObject):
        """
        Transform from a question bank to a regular question set.
        """
        self._pre_flight_validation(contentObject, structural_change=True)
        result = QQuestionSet()
        self._copy_to_new_type(contentObject, result)
        self._re_register(result, IQuestionBank, IQuestionSet)
        return result

    def _update_bank_status(self, externalValue, contentObject):
        """
        Determine if our object is transitioning to/from a question bank.
        """
        if 'draw' in externalValue:
            # The client passed us something; see if we are going to/from
            # question bank.
            draw = externalValue.get('draw')
            if      draw \
                and not IQuestionBank.providedBy(contentObject):
                contentObject = self._transform_to_bank(contentObject)
            elif    draw is None \
                and IQuestionBank.providedBy(contentObject):
                contentObject = self._transform_to_non_bank(contentObject)
            elif    draw \
                and contentObject.draw is not None \
                and contentObject.draw != draw:
                # Changing draw counts; validate structurally.
                self._pre_flight_validation(contentObject,
                                            structural_change=True)
            # Update our context
            self.context = contentObject
        return self.context

    def updateContentObject(self, contentObject, externalValue, **kwargs):
        # Must do this first to get the actual object we are creating/updating.
        new_contentObject = self._update_bank_status(externalValue, contentObject)
        result = super(QuestionSetPutView, self).updateContentObject(new_contentObject,
                                                                     externalValue,
                                                                     **kwargs)
        return result

    def __call__(self):
        # Override to control what is returned.
        super(QuestionSetPutView, self).__call__()
        return self.context


class NewAndLegacyPutView(EvaluationMixin, AssessmentPutView):

    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the object definition.")

    @Lazy
    def course(self):
        result = find_interface(self.context, ICourseInstance, strict=False)
        return result if result is not None else get_course_from_request()

    @property
    def legacy_editable_fields(self):
        # XXX: We allow toggling public status? This is the only
        # change that may lock the assignment from syncing.
        return ('is_non_public',) + self.policy_keys

    def _require_course(self):
        course = get_course_from_request()
        if course is None:
            raise hexc.HTTPForbidden(_(u'Must supply course'))
        return course

    def _validate_instructor_edit(self, externalValue):
        """
        We want to allow instructors to edit their specific course assessment
        policies.
        """
        course = self._require_course()
        if not is_course_instructor(course, self.remoteUser):
            raise hexc.HTTPForbidden()
        non_policy_edits = bool(set(externalValue.keys()) - set(self.policy_keys))
        if non_policy_edits:
            raise hexc.HTTPForbidden(_(u'Instructors can only edit policy fields.'))

    def _validate_permissions(self, obj, externalValue):
        """
        This is our permission checking for PUTS on assignments. Editors
        get full WRITE access, while instructors only get to edit
        assignment policy fields.
        """
        is_editor = has_permission(nauth.ACT_CONTENT_EDIT, obj, self.request)
        if not is_editor:
            self._validate_instructor_edit(externalValue)

    def _check_object_constraints(self, obj, externalValue, preflight=True):
        self._validate_permissions(obj, externalValue)
        editing_keys = set(externalValue.keys())
        if      not IQEditableEvaluation.providedBy(obj) \
            and editing_keys - set(self.legacy_editable_fields):
            # Cannot edit content backed assessment objects (except
            # for policy keys).
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': self.OBJ_DEF_CHANGE_MSG,
                                 'code': 'CannotChangeObjectDefinition',
                             },
                             None)
        super(NewAndLegacyPutView, self)._check_object_constraints(obj, externalValue)

        if preflight:
            self._pre_flight_validation(obj, externalValue)

    def readInput(self, value=None):
        result = AssessmentPutView.readInput(self, value=value)
        for key in (VERSION,):
            result.pop(key, None)
            result.pop(key.lower(), None)
        return result

    def _get_post_update_source(self, externalValue):
        return externalValue, copy.deepcopy(externalValue)

    def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
        originalSource = copy.deepcopy(externalValue)
        externalValue, update_source = self._get_post_update_source(externalValue)
        result = AssessmentPutView.updateContentObject(self,
                                                       contentObject,
                                                       externalValue,
                                                       set_id=set_id,
                                                       notify=False)
        self.post_update_check(contentObject, update_source)
        sources = get_all_sources(self.request)
        if sources:
            validate_sources(self.remoteUser, result.model, sources)

        if IQEditableEvaluation.providedBy(contentObject):
            self.handle_evaluation(contentObject, self.composite,
                                   sources, self.remoteUser)
        # validate changes, subscribers
        if notify:
            self.notify_and_record(contentObject, originalSource)
        return result


@view_config(route_name='objects.generic.traversal',
             context=IQPoll,
             request_method='PUT',
             renderer='rest')
class PollPutView(NewAndLegacyPutView):

    TO_AVAILABLE_MSG = _(u'Poll will become available. Please confirm.')
    TO_UNAVAILABLE_MSG = _(u'Poll will become unavailable. Please confirm.')
    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the poll definition.")


@view_config(route_name='objects.generic.traversal',
             context=IQPoll,
             request_method='PUT',
             name='preflight',
             renderer='rest')
class UpdatePollPreflightView(PollPutView):

    def _check_structural_change(self, context, externalValue):
        self._structural_change = \
            PollPutView._check_structural_change(self, context, externalValue)
        return self._structural_change

    def __call__(self, *args, **kwargs):
        try:
            super(UpdatePollPreflightView, self).__call__(*args, **kwargs)

            return {
                'StructuralChanges': self._structural_change
            }
        finally:
            self.request.environ['nti.commit_veto'] = 'abort'


@view_config(route_name='objects.generic.traversal',
             context=IQSurvey,
             request_method='PUT',
             renderer='rest')
class SurveyPutView(NewAndLegacyPutView):

    TO_AVAILABLE_MSG = _(u'Survey will become available. Please confirm.')
    TO_UNAVAILABLE_MSG = _(u'Survey will become unavailable. Please confirm.')
    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the survey definition.")

    CAN_FORCE_STRUCTURAL_EDITS = True

    # XXX: Should we extend the parent set here?
    NON_DATE_POLICY_KEYS = ('disclosure', 'full_submission')

    def _skip_solution_check_proxy(self, obj):
        return IQAvoidSolutionCheck(obj)

    def _clear_submissions(self):
        delete_inquiry_submissions(self.context, self.course)

    @property
    def _reset_submissions(self):
        params = CaseInsensitiveDict(self.request.params)
        return is_true(params.get('force'))

    def _validate_structural_edits(self, context=None):
        if self._reset_submissions:
            self._clear_submissions()

        super(SurveyPutView, self)._validate_structural_edits(context)

    def _update_polls(self, externalValue, notify=True):
        """
        Allow updating the entire survey in one shot, including updates
        to underlying polls.

        We need the original externalized content so can determine whether
        an update is intended
        """

        ext_questions = externalValue.get('questions')
        for i, ext_question in tuple(enumerate(ext_questions or ())):  # modifying

            if not isinstance(ext_question, Mapping):
                continue

            # Ignore policy key updates
            for key in self.policy_keys:
                ext_question.pop(key, None)

            ntiid = ext_question.get(INTERNAL_NTIID) or ext_question.get(NTIID)
            poll = self.get_registered_evaluation(ntiid, self.composite)

            # No ntiid or no object found with that ntiid
            if poll is None:
                continue

            # Need to skip solution check during notifications
            if not _ntiid_only(ext_question):

                # Don't repeat the preflight checks we'll make for the survey
                self._check_object_constraints(poll, externalValue, preflight=False)

                ext_update = copy.deepcopy(ext_question)
                poll = update_object_from_external_object(poll,
                                                          ext_update,
                                                          notify=False,
                                                          request=self.request)

                if notify:
                    ext_notify = copy.deepcopy(ext_question)
                    self.notify_and_record(poll, ext_notify)

            # Since polls contain only fields to be updated, they
            # may not properly internalize later in the process, so
            # we replace them with an OID that will resolve to the
            # full object (b/c of __external_oids__ in the survey
            # internalizer)
            ext_questions[i] = to_external_ntiid_oid(poll)

    def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
        self._update_polls(externalValue)

        result = NewAndLegacyPutView.updateContentObject(self,
                                                       contentObject,
                                                       externalValue,
                                                       set_id=set_id)

        return result

    def post_update_check(self, contentObject, originalSource):
        if IQEditableEvaluation.providedBy(contentObject):
            items = originalSource.get(ITEMS)
            if items:  # list of ntiids
                contentObject.questions = indexed_iter()  # reset
                self.auto_complete_survey(contentObject, originalSource)
        super(SurveyPutView, self).post_update_check(contentObject, originalSource)


@view_config(route_name='objects.generic.traversal',
             context=IQAssignment,
             request_method='PUT',
             renderer='rest')
class AssignmentPutView(NewAndLegacyPutView):

    TO_AVAILABLE_MSG = _(u'Assignment will become available. Please confirm.')
    TO_UNAVAILABLE_MSG = _(u'Assignment will become unavailable. Please confirm.')
    OBJ_DEF_CHANGE_MSG = _(u"Cannot change the assignment definition.")

    def _check_object_constraints(self, obj, externalValue):
        super(AssignmentPutView, self)._check_object_constraints(obj, externalValue)
        parts = externalValue.get('parts')
        if parts:
            self._validate_structural_edits()

    def _get_post_update_source(self, externalValue):
        """
        If our question set just has ntiids, pop from original (in order
        to update without 422ing) and return items for postUpdate.
        """
        result = dict()
        # Assuming one part per assignment.
        for part in externalValue.get('parts') or ():
            qset = part.get('question_set')
            if _assignment_part_with_question_set_ntiid_only(part):
                # Populate a placeholder question set to pass validation.
                # We'll fill in this with the question set corresponding
                # to this ntiid after update.
                result['question_set'] = part.pop('question_set')
                part['question_set'] = {'MimeType': QQuestionSet.mime_type}
            else:
                ntiids_only = _qset_with_ntiids_only(qset) if qset else None
                if ntiids_only:
                    result[ITEMS] = qset.pop('questions')
        return externalValue, result

    def post_update_check(self, contentObject, originalSource):
        if IQEditableEvaluation.providedBy(contentObject):
            if originalSource:  # list of ntiids
                for qset in contentObject.iter_question_sets():  # reset
                    qset.questions = indexed_iter()
                self.auto_complete_assignment(contentObject, originalSource)
        # Must complete our set first.
        super(AssignmentPutView, self).post_update_check(
            contentObject, originalSource)

    def _transform_to_timed(self, contentObject):
        """
        Transform from a regular assignment to a timed assignment. This is a
        policy change on the course so we allow these even if we have
        submissions/savepoints.
        """
        interface.alsoProvides(contentObject, IQTimedAssignment)
        contentObject.mimeType = contentObject.mime_type = TIMED_ASSIGNMENT_MIME_TYPE
        self._re_register(contentObject, IQAssignment, IQTimedAssignment)

    def _transform_to_untimed(self, contentObject):
        """
        Transform from a timed assignment to a regular assignment. This is a
        policy change on the course so we allow these even if we have
        submissions/savepoints.
        """
        interface.noLongerProvides(contentObject, IQTimedAssignment)
        contentObject.mimeType = contentObject.mime_type = ASSIGNMENT_MIME_TYPE
        self._re_register(contentObject, IQTimedAssignment, IQAssignment)

    def _update_timed_status(self, externalValue, contentObject):
        """
        Determine if our object is transitioning to/from a timed assignment.
        Only editors can toggle state on API created assignments.
        """
        if      'maximum_time_allowed' in externalValue \
            and IQEditableEvaluation.providedBy(contentObject) \
            and has_permission(nauth.ACT_CONTENT_EDIT, contentObject, self.request):
            if IQDiscussionAssignment.providedBy(contentObject):
                raise_json_error(self.request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                     'message': _(u"Cannot transform discussion assignment."),
                                     'code': 'CannotTransformAssignment',
                                 },
                                 None)

            # The client passed us something; see if we are going to/from timed
            # assignment.
            max_time_allowed = externalValue.get('maximum_time_allowed')
            if      max_time_allowed \
                and not IQTimedAssignment.providedBy(contentObject):
                self._transform_to_timed(contentObject)
                # This field is an assignment policy field, we need to set a
                # default value in our object itself that will get overridden
                # by the policy.
                if not getattr(contentObject, 'maximum_time_allowed', None):
                    contentObject.maximum_time_allowed = max_time_allowed
            elif    max_time_allowed is None \
                and IQTimedAssignment.providedBy(contentObject):
                self._transform_to_untimed(contentObject)

    def _validate_timed(self, contentObject, externalValue):
        """
        Validate that, when making time-allowed changes, we do not currently
        have users taking this assignment.
        """
        max_time_allowed = externalValue.get('maximum_time_allowed')
        current_time_allowed = None
        if IQTimedAssignment.providedBy(contentObject):
            current_time_allowed = get_max_time_allowed(contentObject, self.course)
        if      'maximum_time_allowed' in externalValue \
            and max_time_allowed != current_time_allowed:
            if IQEditableEvaluation.providedBy(contentObject):
                self._pre_flight_validation(contentObject, externalValue,
                                            structural_change=True)
            else:
                # We do not want to try to version bump content-backed
                # assignments that might be shared between courses.
                self._validate_structural_edits(contentObject)

    def _validate_non_public(self, contentObject, externalValue):
        """
        Validate that, when making is_non_public changes, we have users
        enrolled in that scope (or we force it).
        """
        new_non_public = externalValue.get('is_non_public')
        new_non_public = new_non_public and is_true(new_non_public)
        if      new_non_public \
            and new_non_public != contentObject.is_non_public \
            and not is_true(self.request.params.get('force_is_non_public', False)):
            enrollments = ICourseEnrollments(self.course)
            if not enrollments.count_legacy_forcredit_enrollments():
                self._raise_conflict_error('InvalidNonPublicAssignmentScope',
                                           _(u'No users enrolled for credit in this course. Please confirm.'),
                                           self.course,
                                           contentObject.ntiid,
                                           force_flag_name='force_is_non_public')

    def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
        # Must toggle types first (if necessary) before calling super;
        # so everything validates.
        self._validate_non_public(contentObject, externalValue)
        self._validate_timed(contentObject, externalValue)
        self._update_timed_status(externalValue, contentObject)
        result = super(AssignmentPutView, self).updateContentObject(contentObject,
                                                                    externalValue,
                                                                    set_id, notify)
        return result
