#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from zope import component
from zope import lifecycleevent

from zope.event import notify

from zc.intid.interfaces import IBeforeIdRemovedEvent

from zope.intid.interfaces import IIntIdAddedEvent
from zope.intid.interfaces import IIntIdRemovedEvent

from zope.lifecycleevent import ObjectModifiedEvent
from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import regrade_evaluation
from nti.app.assessment.common import get_evaluation_courses
from nti.app.assessment.common import delete_all_evaluation_data
from nti.app.assessment.common import get_course_from_evaluation
from nti.app.assessment.common import get_evaluation_containment
from nti.app.assessment.common import delete_all_evaluation_policy_data
from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations import raise_error

from nti.app.assessment.evaluations.adapters import evaluations_for_course

from nti.app.assessment.evaluations.utils import validate_structural_edits

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer
from nti.app.assessment.interfaces import IRegradeEvaluationEvent

from nti.app.assessment.utils import get_course_from_request

from nti.app.authentication import get_remote_user

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQSubmittable
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer
from nti.assessment.interfaces import IQAssessmentPoliciesModified
from nti.assessment.interfaces import IQuestionInsertedInContainerEvent
from nti.assessment.interfaces import IQuestionRemovedFromContainerEvent

from nti.assessment.interfaces import UnlockQAssessmentPolicies

from nti.contenttypes.courses.common import get_course_site_registry

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.interfaces import IObjectModifiedFromExternalEvent

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.recorder.interfaces import TRX_TYPE_CREATE

from nti.recorder.interfaces import IRecordable
from nti.recorder.interfaces import IObjectUnlockedEvent
from nti.recorder.interfaces import IRecordableContainer

from nti.recorder.utils import record_transaction

from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface


@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, unused_event):
    evaluations_for_course(course)


def _update_containment(item, intids=None):
    for container in get_evaluation_containment(item.ntiid, intids=intids):
        if IQEvaluationItemContainer.providedBy(container):
            container.remove(item)
            lifecycleevent.modified(container)


@component.adapter(IQuestion, IObjectRemovedEvent)
def _on_question_removed(question, unused_event):
    _update_containment(question)


@component.adapter(IQPoll, IObjectRemovedEvent)
def _on_poll_removed(poll, unused_event):
    _update_containment(poll)


@component.adapter(IQEditableEvaluation, IIntIdAddedEvent)
def _on_editable_eval_created(context, event):
    if IRecordable.providedBy(context) and event.principal:
        record_transaction(context, type_=TRX_TYPE_CREATE)


def _validate_part_resource(resource):
    check_solutions = not IQAvoidSolutionCheck.providedBy(resource)
    for part in resource.parts or ():
        analyzer = IQPartChangeAnalyzer(part, None)
        if analyzer is not None:
            analyzer.validate(check_solutions=check_solutions)


def _allow_poll_change(question, externalValue):
    parts = externalValue.get('parts')
    course = find_interface(question, ICourseInstance, strict=False)
    if parts and has_submissions(question, course):
        for part, change in zip(question.parts, parts):
            analyzer = IQPartChangeAnalyzer(part, None)
            if analyzer is not None:
                if not analyzer.allow(change, check_solutions=False):
                    raise_error(
                        {
                            'message': _(u"Poll has submissions. It cannot be updated."),
                            'code': 'CannotChangeObjectDefinition',
                        })


@component.adapter(IQuestion, IObjectAddedEvent)
def _on_question_added(question, unused_event):
    if IQEditableEvaluation.providedBy(question):
        _validate_part_resource(question)


@component.adapter(IQuestion, IObjectModifiedFromExternalEvent)
def _on_question_modified(question, unused_event):
    if IQEditableEvaluation.providedBy(question):
        _validate_part_resource(question)


@component.adapter(IQEditableEvaluation, IQuestionInsertedInContainerEvent)
def _on_question_inserted_in_container(container, unused_event):
    course = find_interface(container, ICourseInstance, strict=False)
    validate_structural_edits(container, course)
    if IRecordableContainer.providedBy(container):
        container.childOrderLock()
    # Now update any assignments for our container
    assignments = get_assignments_for_evaluation_object(container)
    for assignment in assignments or ():
        notify(ObjectModifiedEvent(assignment))


@component.adapter(IQEditableEvaluation, IQuestionRemovedFromContainerEvent)
def _on_question_removed_from_container(container, unused_event):
    _on_question_inserted_in_container(container, None)


@component.adapter(IQPoll, IObjectAddedEvent)
def _on_poll_added(poll, unused_event):
    if IQEditableEvaluation.providedBy(poll):
        _validate_part_resource(poll)


@component.adapter(IQPoll, IObjectModifiedFromExternalEvent)
def _on_poll_modified(poll, unused_event):
    if IQEditableEvaluation.providedBy(poll):
        _validate_part_resource(poll)
        _allow_poll_change(poll)


@component.adapter(IQuestionSet, IObjectAddedEvent)
@component.adapter(IQuestionSet, IObjectModifiedFromExternalEvent)
def _on_questionset_event(context, unused_event):
    if      IQEditableEvaluation.providedBy(context) \
        and not context.questions:
        raise_error({
            'message': _(u"QuestionSet cannot be empty."),
            'code': 'EmptyQuestionSet',
        })


@component.adapter(IQSurvey, IObjectAddedEvent)
@component.adapter(IQSurvey, IObjectModifiedFromExternalEvent)
def _on_survey_event(context, unused_event):
    if      IQEditableEvaluation.providedBy(context) \
        and not context.questions:
        raise_error({
            'message': _(u"Survey cannot be empty."),
            'code': 'EmptyQuestionSet',
        })


@component.adapter(IQEvaluation, IRegradeEvaluationEvent)
def _on_regrade_evaluation_event(context, unused_event):
    course = get_course_from_request()
    if course is None:
        course = get_course_from_evaluation(context, user=get_remote_user())
    if course is not None:
        regrade_evaluation(context, course)


@component.adapter(ICourseInstance, IQAssessmentPoliciesModified)
def _on_assessment_policies_modified_event(course, event):
    assesment = event.assesment
    if isinstance(assesment, six.string_types):
        assesment = find_object_with_ntiid(assesment)
    if IQAssignment.providedBy(assesment):
        # If they're enabling auto_grade or specifying a new
        # total points value, trigger a regrade.
        if      event.key.lower() in ('total_points', 'auto_grade') \
            and event.value:
            regrade_evaluation(assesment, course)


@component.adapter(IQAssignment, IObjectUnlockedEvent)
def _on_assignment_unlock_event(context, unused_event):
    courses = get_evaluation_courses(context)
    notify(UnlockQAssessmentPolicies(context, courses))


@component.adapter(IQEditableEvaluation, IBeforeIdRemovedEvent)
def _on_editable_evaluation_removed(context, unused_event):
    if IQSubmittable.providedBy(context):
        delete_all_evaluation_data(context)
    else:
        delete_all_evaluation_policy_data(context)


@component.adapter(ICourseInstance, IIntIdRemovedEvent)
def _on_course_instance_removed(course, unused_event):
    evaluations = ICourseEvaluations(course, None)
    if evaluations is not None:
        registry = get_course_site_registry(course)
        for obj in list(evaluations.values()):
            provided = iface_of_assessment(obj)
            unregisterUtility(registry, provided=provided, name=obj.ntiid)
        evaluations.clear()
on_course_instance_removed = _on_course_instance_removed # BWC
