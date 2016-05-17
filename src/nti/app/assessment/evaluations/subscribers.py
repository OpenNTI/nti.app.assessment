#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import lifecycleevent

from zope.event import notify

from zope.intid.interfaces import IIntIdAddedEvent

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import evaluation_submissions
from nti.app.assessment.common import get_evaluation_containment

from nti.app.assessment.evaluations import raise_error

from nti.app.assessment.evaluations.adapters import evaluations_for_course

from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer
from nti.app.assessment.interfaces import IRegradeQuestionEvent
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.interfaces import ObjectRegradeEvent
from nti.app.assessment.interfaces import RegradeQuestionEvent

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.coremetadata.interfaces import IRecordable

from nti.externalization.interfaces import IObjectModifiedFromExternalEvent

from nti.recorder.interfaces import TRX_TYPE_CREATE

from nti.recorder.utils import record_transaction

from nti.traversal.traversal import find_interface

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	evaluations_for_course(course)

def _update_containment(item, intids=None):
	for container in get_evaluation_containment(item.ntiid, intids=intids):
		if IQEvaluationItemContainer.providedBy(container):
			container.remove(item)
			lifecycleevent.modified(container)

@component.adapter(IQuestion, IObjectRemovedEvent)
def _on_question_removed(question, event):
	_update_containment(question)

@component.adapter(IQPoll, IObjectRemovedEvent)
def _on_poll_removed(poll, event):
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

def _allow_question_change(question, externalValue):
	parts = externalValue.get('parts')
	check_solutions = not IQAvoidSolutionCheck.providedBy(question)
	course = find_interface(question, ICourseInstance, strict=False)
	if parts and has_submissions(question, course):
		regrade = []
		for part, change in zip(question.parts, parts):
			analyzer = IQPartChangeAnalyzer(part, None)
			if analyzer is not None:
				if not analyzer.allow(change, check_solutions=check_solutions):
					raise_error(
						{
							u'message': _("Question has submissions. It cannot be updated."),
							u'code': 'CannotChangeObjectDefinition',
						})
				if analyzer.regrade(change):
					regrade.append(part)
		if regrade:
			notify(RegradeQuestionEvent(question, regrade))

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
							u'message': _("Poll has submissions. It cannot be updated."),
							u'code': 'CannotChangeObjectDefinition',
						})

@component.adapter(IQuestion, IObjectAddedEvent)
def _on_question_added(question, event):
	if IQEditableEvaluation.providedBy(question):
		_validate_part_resource(question)

@component.adapter(IQuestion, IObjectModifiedFromExternalEvent)
def _on_question_modified(question, event):
	if IQEditableEvaluation.providedBy(question):
		_validate_part_resource(question)
		_allow_question_change(question, event.external_value)

@component.adapter(IQPoll, IObjectAddedEvent)
def _on_poll_added(poll, event):
	if IQEditableEvaluation.providedBy(poll):
		_validate_part_resource(poll)

@component.adapter(IQPoll, IObjectModifiedFromExternalEvent)
def _on_poll_modified(poll, event):
	if IQEditableEvaluation.providedBy(poll):
		_validate_part_resource(poll)
		_allow_poll_change(poll)

@component.adapter(IQuestionSet, IObjectAddedEvent)
@component.adapter(IQuestionSet, IObjectModifiedFromExternalEvent)
def _on_questionset_event(context, event):
	if 		IQEditableEvaluation.providedBy(context) \
		and not context.questions:
		raise_error({
						u'message': _("QuestionSet cannot be empty."),
						u'code': 'EmptyQuestionSet',
					})

@component.adapter(IQSurvey, IObjectAddedEvent)
@component.adapter(IQSurvey, IObjectModifiedFromExternalEvent)
def _on_survey_event(context, event):
	if 		IQEditableEvaluation.providedBy(context) \
		and not context.questions:
		raise_error({
						u'message': _("Survey cannot be empty."),
						u'code': 'EmptyQuestionSet',
					})

@component.adapter(IQuestion, IRegradeQuestionEvent)
def _on_regrade_question_event(context, event):
	course = ICourseInstance(context, None)
	if course is not None:
		seen = set()
		for item in evaluation_submissions(context, course):
			if not IUsersCourseAssignmentHistoryItem.providedBy(item):
				continue
			assignmentId = item.__name__ # by def
			if assignmentId in seen: # safety
				continue
			seen.add(assignmentId)
			notify(ObjectRegradeEvent(item))
