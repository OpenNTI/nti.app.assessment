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

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.evaluations import raise_error

from nti.app.assessment.interfaces import IQPartChangeAnalyzer

from nti.assessment.interfaces import IQGradablePart
from nti.assessment.interfaces import IQNonGradableFilePart
from nti.assessment.interfaces import IQNonGradableConnectingPart
from nti.assessment.interfaces import IQNonGradableFreeResponsePart
from nti.assessment.interfaces import IQNonGradableMultipleChoicePart
from nti.assessment.interfaces import IQNonGradableMultipleChoiceMultipleAnswerPart

from nti.common.sets import OrderedSet

from nti.externalization.externalization import to_external_object

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