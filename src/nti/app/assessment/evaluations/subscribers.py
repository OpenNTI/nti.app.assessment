#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from zope import component
from zope import lifecycleevent

from zope.event import notify

from zope.intid.interfaces import IIntIdAddedEvent

from zope.lifecycleevent import ObjectModifiedEvent
from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from persistent.list import PersistentList

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import evaluation_submissions
from nti.app.assessment.common import get_course_from_evaluation
from nti.app.assessment.common import get_evaluation_containment
from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations import raise_error

from nti.app.assessment.evaluations.adapters import evaluations_for_course

from nti.app.assessment.evaluations.utils import validate_structural_edits

from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer
from nti.app.assessment.interfaces import IRegradeQuestionEvent
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.interfaces import ObjectRegradeEvent

from nti.app.assessment.utils import get_course_from_request

from nti.app.authentication import get_remote_user

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessedQuestion
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer
from nti.assessment.interfaces import IQAssessmentPoliciesModified
from nti.assessment.interfaces import IQuestionInsertedInContainerEvent
from nti.assessment.interfaces import IQuestionRemovedFromContainerEvent

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.coremetadata.interfaces import IRecordable
from nti.coremetadata.interfaces import IRecordableContainer

from nti.externalization.interfaces import IObjectModifiedFromExternalEvent

from nti.ntiids.ntiids import find_object_with_ntiid

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

@component.adapter(IQEditableEvaluation, IQuestionInsertedInContainerEvent)
def _on_question_inserted_in_container(container, event):
	course = find_interface(container, ICourseInstance, strict=False)
	validate_structural_edits(container, course)
	if IRecordableContainer.providedBy(container):
		container.child_order_locked = True
	# Now update any assignments for our container
	assignments = get_assignments_for_evaluation_object( container )
	for assignment in assignments or ():
		notify( ObjectModifiedEvent( assignment ) )

@component.adapter(IQEditableEvaluation, IQuestionRemovedFromContainerEvent)
def _on_question_removed_from_container(container, event):
	_on_question_inserted_in_container(container, None)

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

def _reassess_submission(item, question_updated):
	"""
	Update our submission by re-assessing the changed question.
	"""
	assignment_submission = item.Submission
	pending_assessment = item.pendingAssessment
	if assignment_submission is None or pending_assessment is None:
		return

	assessed_question = None
	for part in assignment_submission.parts or ():
		for question_submission in part.questions or ():
			if question_submission.questionId == question_updated.ntiid:
				assessed_question = IQAssessedQuestion(question_submission)
				break

	if assessed_question is None:
		logger.warn(
			'Cannot find question in submission to re-assess (assignment=%s) (user=%s) (question=%s)',
			assignment_submission.assignmentId,
			assignment_submission.creator,
			question_updated.ntiid )
		return

	for part in pending_assessment.parts or ():
		updated = False
		new_questions = PersistentList()
		for asub_question in part.questions or ():
			if asub_question.questionId == question_updated.ntiid:
				asub_question = assessed_question
				updated = True
			new_questions.append(asub_question)
		if updated:
			part.questions = new_questions
			return

	logger.warn('Cannot find question in assessment (assignment=%s) (user=%s) (question=%s)',
				assignment_submission.assignmentId,
				assignment_submission.creator,
				question_updated.ntiid )

def _regrade_assesment(context, course):
	result = []
	for item in evaluation_submissions(context, course):
		if not IUsersCourseAssignmentHistoryItem.providedBy(item):
			continue
		result.append(item)
		_reassess_submission( item, context )
		# Now broadcast we need a new grade
		notify(ObjectRegradeEvent(item))
	return result

@component.adapter(IQuestion, IRegradeQuestionEvent)
def _on_regrade_question_event(context, event):
	request = get_current_request()
	course = get_course_from_request(request) if request else None
	if course is None:
		course = get_course_from_evaluation(context, user=get_remote_user())
	if course is not None:
		_regrade_assesment(context, course)

@component.adapter(ICourseInstance, IQAssessmentPoliciesModified)
def _on_assessment_policies_modified_event(course, event):
	assesment = event.assesment
	if isinstance(assesment, six.string_types):
		assesment = find_object_with_ntiid(assesment)
	if IQAssignment.providedBy(assesment) and 'total_points' == event.key:
		if event.value:
			_regrade_assesment(assesment, course)
