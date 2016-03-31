#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.annotation.interfaces import IAnnotations

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from pyramid import httpexceptions as hexc

from pyramid.interfaces import IRequest

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.common import get_evaluation_containment

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IQPartChangeAnalyzer

from nti.app.externalization.error import raise_json_error

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQEditable
from nti.assessment.interfaces import IQNonGradablePart
from nti.assessment.interfaces import IQEvaluationItemContainer
from nti.assessment.interfaces import IQNonGradableFreeResponsePart
from nti.assessment.interfaces import IQNonGradableMultipleChoicePart
from nti.assessment.interfaces import IQNonGradableMultipleChoiceMultipleAnswerPart

from nti.common.sets import OrderedSet

from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_editors

from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.externalization.externalization import to_external_object

from nti.traversal.traversal import find_interface

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

@interface.implementer(ICourseInstance)
@component.adapter(ICourseEvaluations)
def _course_from_item_lineage(item):
	return course_from_context_lineage(item, validate=True)

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_evaluations_for_course(course)

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

# Part change analyzers

def _validate_question(question):
	for part in question.parts or ():
		analyzer = IQPartChangeAnalyzer(part, None)
		if analyzer is not None:
			analyzer.validate()

@component.adapter(IQuestion, IObjectAddedEvent)
def _on_question_added(question, event):
	if IQEditable.providedBy(question):
		_validate_question(question)

@component.adapter(IQuestion, IObjectModifiedEvent)
def _on_question_modified(question, event):
	if IQEditable.providedBy(question):
		_validate_question(question)

def raise_error(v, tb=None, factory=hexc.HTTPUnprocessableEntity,):
	request = get_current_request()
	raise_json_error(request, factory, v, tb)

@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableMultipleChoicePart)
class _MultipleChoicePartChangeAnalyzer(object):

	def __init__(self, part):
		self.part = part

	def validate_solutions(self, part):
		solutions = part.solutions
		if not solutions:
			raise raise_error({ u'message': _("Must specify a solution."),
								u'code': 'MissingSolutions'})
		choices = set(c.lower() for c in part.choices)
		for solution in solutions:
			if solution.lower() not in choices:
				raise raise_error({ u'message': _("Solution in not in choices."),
									u'code': 'InvalidSolution'})

	def validate(self, part=None):
		part = self.part if part is None else part
		choices = part.choices or ()
		unique_choices = OrderedSet(choices)
		if not choices:
			raise raise_error({ u'message': _("Must specify a choice selection."),
								u'code': 'MissingPartChoices'})
		if len(choices) != len(unique_choices):
			raise raise_error({ u'message': _("Cannot have duplicate choices."),
								u'code': 'DuplicatePartChoices'})
		self.validate_solutions(part)

	def allow(self, change):
		if IQNonGradablePart.providedBy(change):
			change = to_external_object(change)
		old_choices = self.part.choices
		new_choices = OrderedSet(change.get('choices') or ())
		# cannot substract choices
		if len(new_choices) < len(old_choices):
			return False
		for idx, data in enumerate(zip(old_choices, new_choices)):
			old, new = data
			# label change, make sure we are not reordering
			if old != new and new in old_choices[idx + 1:]:
				return False
		return True

@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableMultipleChoiceMultipleAnswerPart)
class _MultipleChoiceMultiplePartChangeAnalyzer(_MultipleChoicePartChangeAnalyzer):

	def validate_solutions(self, part):
		multiple_choice_solutions = part.solutions
		if not multiple_choice_solutions:
			raise raise_error({ u'message': _("Must specify a solution set."),
								u'code': 'MissingSolutions'})
		for solutions in multiple_choice_solutions:
			if not solutions:
				raise raise_error({ u'message': _("Solution set cannot be empty."),
									u'code': 'MissingSolutions'})
			choices = set(c.lower() for c in part.choices)
			for solution in solutions:
				if not solution:
					raise raise_error({ u'message': _("Solution cannot be empty."),
										u'code': 'InvalidSolution'})
				if solution.lower() not in choices:
					raise raise_error({ u'message': _("Solution in not in choices."),
										u'code': 'InvalidSolution'})

@interface.implementer(IQPartChangeAnalyzer)
@component.adapter(IQNonGradableFreeResponsePart)
class _FreeResponsePartChangeAnalyzer(object):

	def validate(self, part=None):
		solutions = part.solutions
		if not solutions:
			raise raise_error({ u'message': _("Must specify a solution."),
								u'code': 'MissingSolutions'})
		for solution in solutions:
			if not solution:
				raise raise_error({ u'message': _("Solution cannot be empty."),
									u'code': 'InvalidSolution'})

	def allow(self, change):
		return True  # always allow
