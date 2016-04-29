#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import Mapping

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.annotation.interfaces import IAnnotations

from zope.event import notify

from zope.intid.interfaces import IIntIdAddedEvent

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from pyramid import httpexceptions as hexc

from pyramid.interfaces import IRequest

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import evaluation_submissions 
from nti.app.assessment.common import get_evaluation_containment

from nti.app.assessment.interfaces import ICourseEvaluations,\
	IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer
from nti.app.assessment.interfaces import IRegradeQuestionEvent
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.interfaces import ObjectRegradeEvent
from nti.app.assessment.interfaces import RegradeQuestionEvent

from nti.app.externalization.error import raise_json_error

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQGradablePart
from nti.assessment.interfaces import IQEditableEvalutation
from nti.assessment.interfaces import IQNonGradableFilePart
from nti.assessment.interfaces import IQEvaluationItemContainer
from nti.assessment.interfaces import IQNonGradableConnectingPart
from nti.assessment.interfaces import IQNonGradableFreeResponsePart
from nti.assessment.interfaces import IQNonGradableMultipleChoicePart
from nti.assessment.interfaces import IQNonGradableMultipleChoiceMultipleAnswerPart

from nti.common.sets import OrderedSet

from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_editors

from nti.coremetadata.interfaces import IRecordable

from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import IObjectModifiedFromExternalEvent

from nti.recorder.interfaces import TRX_TYPE_CREATE

from nti.recorder.utils import record_transaction

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable

@interface.implementer(ICourseEvaluations)
class CourseEvaluations(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course evaluations.
	"""

	__external_can_create__ = False

	@property
	def Items(self):
		return dict(self)

	@property
	def __acl__(self):
		aces = [ ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, self),
				 ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
		course = find_interface(self.context, ICourseInstance, strict=False)
		if course is not None:
			aces.extend(ace_allowing(i, ALL_PERMISSIONS, type(self))
						for i in course.instructors)
			aces.extend(ace_allowing(i, ALL_PERMISSIONS, type(self))
						for i in get_course_editors(course))
		aces.append(ACE_DENY_ALL)
		result = acl_from_aces(aces)
		return result

@component.adapter(ICourseInstance)
@interface.implementer(ICourseEvaluations)
def _evaluations_for_course(course, create=True):
	result = None
	annotations = IAnnotations(course)
	try:
		KEY = 'CourseEvaluations'
		result = annotations[KEY]
	except KeyError:
		if create:
			result = CourseEvaluations()
			annotations[KEY] = result
			result.__name__ = KEY
			result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IRequest)
def _evaluations_for_course_path_adapter(course, request):
	return _evaluations_for_course(course)

@component.adapter(ICourseEvaluations, IRequest)
class _CourseEvaluationsTraversable(ContainerAdapterTraversable):

	def traverse(self, key, remaining_path):
		return super(_CourseEvaluationsTraversable, self).traverse(key, remaining_path)

@interface.implementer(ICourseInstance)
@component.adapter(ICourseEvaluations)
def _course_from_item_lineage(item):
	return course_from_context_lineage(item, validate=True)

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_evaluations_for_course(course)

@interface.implementer(ICourseInstance)
@component.adapter(IQEditableEvalutation)
def _editable_evaluation_to_course(resource):
	return find_interface(resource, ICourseInstance, strict=False)

# subscribers

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

@component.adapter(IQEditableEvalutation, IIntIdAddedEvent)
def _on_editable_eval_created(context, event):
	if IRecordable.providedBy(context) and event.principal:
		record_transaction(context, type_=TRX_TYPE_CREATE)

# misc errors

def raise_error(v, tb=None, factory=hexc.HTTPUnprocessableEntity):
	request = get_current_request()
	raise_json_error(request, factory, v, tb)

# Part change analyzers

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
							u'message': _("Question has submissions. It cannot be updated"),
							u'code': 'CannotChangeObjectDefinition',
						})
				if analyzer.regrade(change):
					regrade.append(part)
		if regrade:
			notify(RegradeQuestionEvent(question, regrade))

def _allow_poll_change(question, externalValue):
	parts = externalValue.get('parts')
	check_solutions = not IQAvoidSolutionCheck.providedBy(question)
	course = find_interface(question, ICourseInstance, strict=False)
	if parts and has_submissions(question, course):
		for part, change in zip(question.parts, parts):
			analyzer = IQPartChangeAnalyzer(part, None)
			if analyzer is not None:
				if not analyzer.allow(change, check_solutions=check_solutions):
					raise_error(
						{
							u'message': _("Poll has submissions. It cannot be updated"),
							u'code': 'CannotChangeObjectDefinition',
						})

@component.adapter(IQuestion, IObjectAddedEvent)
def _on_question_added(question, event):
	if IQEditableEvalutation.providedBy(question):
		_validate_part_resource(question)

@component.adapter(IQuestion, IObjectModifiedFromExternalEvent)
def _on_question_modified(question, event):
	if IQEditableEvalutation.providedBy(question):
		_validate_part_resource(question)
		_allow_question_change(question, event.external_value)

@component.adapter(IQPoll, IObjectAddedEvent)
def _on_poll_added(poll, event):
	if IQEditableEvalutation.providedBy(poll):
		_validate_part_resource(poll)

@component.adapter(IQPoll, IObjectModifiedFromExternalEvent)
def _on_poll_modified(poll, event):
	if IQEditableEvalutation.providedBy(poll):
		_validate_part_resource(poll)
		_allow_poll_change(poll)

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
			
@interface.implementer(IQPartChangeAnalyzer)
class _BasicPartChangeAnalyzer(object):

	def __init__(self, part):
		self.part = part

	def validate(self, part=None, check_solutions=True):
		raise NotImplementedError()

	def allow(self, change, check_solutions=True):
		raise NotImplementedError()

	def regrade(self, change):
		raise False

def to_int(value):
	try:
		return int(value)
	except ValueError:
		raise raise_error({ u'message': _("Invalid integer value."),
							u'code': 'ValueError'})

def to_external(obj):
	if not isinstance(obj, Mapping):
		return to_external_object(obj, decorate=False)
	return obj

def is_gradable(part):
	result = IQGradablePart.providedBy(part)
	return result
	
@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableMultipleChoicePart)
class _MultipleChoicePartChangeAnalyzer(_BasicPartChangeAnalyzer):

	def homogenize(self, value):
		return to_int(value)

	def validate_solutions(self, part):
		solutions = part.solutions
		if not solutions and is_gradable(part):
			raise raise_error({ u'message': _("Must specify a solution."),
								u'code': 'MissingSolutions'})
		for solution in solutions or ():
			if not solution or solution.value is None:
				raise raise_error({ u'message': _("Solution cannot be empty."),
									u'code': 'InvalidSolution'})
			value = to_int(solution.value)  # solutions are indices
			if value < 0 or value >= len(part.choices):
				raise raise_error({ u'message': _("Solution in not in choices."),
									u'code': 'InvalidSolution'})

	def validate(self, part=None, check_solutions=True):
		part = self.part if part is None else part
		choices = part.choices or ()
		unique_choices = OrderedSet(choices)
		if not choices:
			raise raise_error({ u'message': _("Must specify a choice selection."),
								u'code': 'MissingPartChoices'})
		if len(choices) != len(unique_choices):
			raise raise_error({ u'message': _("Cannot have duplicate choices."),
								u'code': 'DuplicatePartChoices'})
		if check_solutions:
			self.validate_solutions(part)

	def allow(self, change, check_solutions=True):
		change = to_external(change)
		# check new choices
		new_choices = change.get('choices')
		if new_choices is not None:
			old_choices = self.part.choices
			new_choices = OrderedSet(new_choices)
			# cannot substract choices
			if len(new_choices) < len(old_choices):
				return False
			for idx, data in enumerate(zip(old_choices, new_choices)):
				old, new = data
				# label change, make sure we are not reordering
				if old != new and new in old_choices[idx + 1:]:
					return False

		# check new new sols
		if check_solutions:
			new_sols = change.get('solutions')
			if new_sols is not None and is_gradable(self.part):
				old_sols = self.part.solutions
				# cannot substract solutions
				if len(new_sols) < len(old_sols):
					return False
		return True

	def regrade(self, change):
		change = to_external(change)
		new_sols = change.get('solutions')
		if new_sols is not None and is_gradable(self.part):
			old_sols = self.part.solutions
			for old, new in zip(old_sols, new_sols):
				# change solution order/value - # int or array of ints
				if self.homogenize(old.value) != self.homogenize(new.get('value')):
					return True
		return False

@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableMultipleChoiceMultipleAnswerPart)
class _MultipleChoiceMultipleAnswerPartChangeAnalyzer(_MultipleChoicePartChangeAnalyzer):

	def homogenize(self, value):
		return tuple(to_int(x) for x in value)

	def validate_solutions(self, part):
		solutions = part.solutions
		if not solutions and is_gradable(part):
			raise raise_error({ u'message': _("Must specify a solution set."),
								u'code': 'MissingSolutions'})
		for solution in solutions or ():
			if not solution or not solution.value:
				raise raise_error({ u'message': _("Solution set cannot be empty."),
									u'code': 'MissingSolutions'})

			unique_solutions = set(solution.value)
			if len(solution.value) > len(unique_solutions):
				raise raise_error({ u'message': _("Cannot have duplicate solution values."),
									u'code': 'DuplicateSolution'})

			for idx in solution.value:
				idx = to_int(idx)
				if idx < 0 or idx >= len(part.choices):  # solutions are indices
					raise raise_error({ u'message': _("Solution in not in choices."),
										u'code': 'InvalidSolution'})

@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableFreeResponsePart)
class _FreeResponsePartChangeAnalyzer(_BasicPartChangeAnalyzer):

	def homogenize(self, value):
		return u'' if not value else value.lower()

	def validate_solutions(self, part):
		solutions = part.solutions
		if not solutions and is_gradable(part):
			raise raise_error({ u'message': _("Must specify a solution."),
								u'code': 'MissingSolutions'})
		for solution in solutions or ():
			if not solution or not solution.value:
				raise raise_error({ u'message': _("Solution cannot be empty."),
									u'code': 'InvalidSolution'})


	def validate(self, part=None, check_solutions=True):
		part = self.part if part is None else part
		if check_solutions:
			self.validate_solutions(part)

	def allow(self, change, check_solutions=True):
		return True  # always allow

	def regrade(self, change):
		change = to_external(change)
		new_sols = change.get('solutions')
		if new_sols is not None and is_gradable(self.part):
			old_sols = self.part.solutions
			for old, new in zip(old_sols, new_sols):
				# change solution order/value
				if self.homogenize(old.value) != self.homogenize(new.get('value')):
					return True
		return False

@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableConnectingPart)
class _ConnectingPartChangeAnalyzer(_BasicPartChangeAnalyzer):

	def homogenize(self, value):
		return {to_int(x):to_int(y) for x, y in value.items()}

	def validate_solutions(self, part, labels, values):
		solutions = part.solutions
		if not solutions and is_gradable(part):
			raise raise_error({ u'message': _("Must specify a solution."),
 								u'code': 'MissingSolutions'})
		for solution in solutions or ():
			if not solution or not solution.value:
				raise raise_error({ u'message': _("Solutions cannot be empty."),
 									u'code': 'InvalidSolution'})

			# map of indices
			m = solution.value

			# check all labels in solution
			if len(m) != len(labels):
				raise raise_error(
						{ u'message': _("Cannot have an incomplete solution."),
						  u'code': 'IncompleteSolution'})

			# check for duplicate values
			unique_values = set(m.values())
			if len(m) > len(unique_values):
				raise raise_error(
						{ u'message': _("Cannot have duplicate solution values."),
						  u'code': 'DuplicateSolution'})

			for label, value in m.items():
				label = to_int(label)
				if label < 0 or label >= len(labels):  # solutions are indices
					raise raise_error(
							{u'message': _("Solution label in not in part labels."),
							 u'code': 'InvalidSolution'})

				value = to_int(value)
				if value < 0 or value >= len(values):  # solutions are indices
					raise raise_error(
							{ u'message': _("Solution value in not in part values."),
							  u'code': 'InvalidSolution'})

	def validate(self, part=None, check_solutions=True):
		part = self.part if part is None else part
		labels = part.labels or ()
		unique_labels = OrderedSet(labels)
		if not labels:
			raise raise_error({ u'message': _("Must specify a label selection."),
								u'code': 'MissingPartLabels'})
		if len(labels) != len(unique_labels):
			raise raise_error({ u'message': _("Cannot have duplicate labels."),
								u'code': 'DuplicatePartLabels'})

		values = part.values or ()
		unique_values = OrderedSet(values)
		if not values:
			raise raise_error({ u'message': _("Must specify a value selection."),
								u'code': 'MissingPartValues'})
		if len(values) != len(unique_values):
			raise raise_error({ u'message': _("Cannot have duplicate values."),
								u'code': 'DuplicatePartValues'})

		if len(labels) != len(values):
			raise raise_error(
					{ u'message': _("Number of labels and values must be equal."),
					  u'code': 'DuplicatePartValues'})

		if check_solutions:
			self.validate_solutions(part, labels, values)

	def _check_selection(self, change, name):
		new_sels = change.get(name)
		if new_sels is not None:
			new_sels = OrderedSet(new_sels)
			old_sels = getattr(self.part, name, None)
			if len(new_sels) != len(old_sels):
				return False
			for idx, data in enumerate(zip(old_sels, new_sels)):
				old, new = data
				if old != new and new in old_sels[idx + 1:]:  # no reordering
					return False
		return True

	def allow(self, change, check_solutions=True):
		change = to_external(change)
		if		not self._check_selection(change, 'labels') \
			or	not self._check_selection(change, 'values'):
			return False

		# check new new_solss
		if check_solutions:
			new_sols = change.get('solutions')
			if new_sols is not None and is_gradable(self.part):
				old_sols = self.part.solutions
				# cannot substract solutions
				if len(new_sols) < len(old_sols):
					return False
		return True

	def regrade(self, change):
		change = to_external(change)
		new_sols = change.get('solutions')
		if new_sols is not None and is_gradable(self.part):
			old_sols = self.part.solutions
			for old, new in zip(old_sols, new_sols):
				# change solution order/value
				if self.homogenize(old.value) != self.homogenize(new.get('value')):  # map of ints
					return True
		return False

@component.adapter(IQNonGradableFilePart)
@interface.implementer(IQPartChangeAnalyzer)
class _FilePartChangeAnalyzer(_BasicPartChangeAnalyzer):

	def validate(self, part=None, check_solutions=True):
		pass

	def allow(self, change, check_solutions=True):
		return True  # always allow
