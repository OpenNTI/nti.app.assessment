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

from nti.app.assessment.decorators import _get_course_from_assignment

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.randomized import randomize
from nti.assessment.randomized import shuffle_list
from nti.assessment.randomized import must_randomize
from nti.assessment.randomized import questionbank_question_chooser
from nti.assessment.randomized import shuffle_matching_part_solutions
from nti.assessment.randomized import shuffle_multiple_choice_part_solutions
from nti.assessment.randomized import shuffle_multiple_choice_multiple_answer_part_solutions

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet
from nti.assessment.randomized.interfaces import IQRandomizedMatchingPart
from nti.assessment.randomized.interfaces import IQRandomizedOrderingPart
from nti.assessment.randomized.interfaces import IQRandomizedMultipleChoicePart
from nti.assessment.randomized.interfaces import IQRandomizedMultipleChoiceMultipleAnswerPart

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import IExternalObjectDecorator

class _AbstractNonEditorRandomizingDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	An abstract decorator that only randomizes if we do not have an instructor or
	an editor, and a non-randomized interface.
	"""

	def _predicate(self, context, result):
		user = self.remoteUser
		course = _get_course_from_assignment(context, user, request=self.request)
		return 		self._is_authenticated \
				and must_randomize( context ) \
				and not has_permission(ACT_CONTENT_EDIT, context, self.request) \
				and not is_course_instructor(course, user) \

@component.adapter(IQRandomizedMatchingPart)
@interface.implementer(IExternalObjectDecorator)
class _QRandomizedMatchingPartDecorator(_AbstractNonEditorRandomizingDecorator):

	def _do_decorate_external(self, context, result):
		generator = randomize(context=context)
		if generator is not None:
			values = list(result['values'])
			shuffle_list(generator, result['values'])
			shuffle_matching_part_solutions(randomize(context=context), # new generator
											values,
											result['solutions'])

@component.adapter(IQRandomizedOrderingPart)
@interface.implementer(IExternalObjectDecorator)
class _QRandomizedOrderingPartDecorator(_QRandomizedMatchingPartDecorator):
	pass

@interface.implementer(IExternalObjectDecorator)
@component.adapter(IQRandomizedMultipleChoicePart)
class _QRandomizedMultipleChoicePartDecorator(_AbstractNonEditorRandomizingDecorator):

	def _do_decorate_external(self, context, result):
		generator = randomize(context=context)
		if generator is not None:
			solutions = result['solutions']
			choices = list(result['choices'])
			shuffle_list(generator, result['choices'])
			shuffle_multiple_choice_part_solutions(randomize(context=context), #  new generator
												   choices,
												   solutions)

@interface.implementer(IExternalObjectDecorator)
@component.adapter(IQRandomizedMultipleChoiceMultipleAnswerPart)
class _QRandomizedMultipleChoiceMultipleAnswerPartDecorator(_AbstractNonEditorRandomizingDecorator):

	def _do_decorate_external(self, context, result):
		generator = randomize(context=context)
		if generator is not None:
			choices = list(result['choices'])
			shuffle_list(generator, result['choices'])
			shuffle_multiple_choice_multiple_answer_part_solutions(randomize(context=context), #  new generator
																   choices,
																   result['solutions'])

@component.adapter(IRandomizedQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _QRandomizedQuestionSetDecorator(_AbstractNonEditorRandomizingDecorator):

	def _do_decorate_external(self, context, result):
		generator = randomize(context=context)
		questions = result.get('questions', ())
		if generator and questions:
			shuffle_list(generator, questions)

@component.adapter(IQuestionBank)
@interface.implementer(IExternalObjectDecorator)
class _QQuestionBankDecorator(_AbstractNonEditorRandomizingDecorator):

	def _do_decorate_external(self, context, result):
		questions = result.get('questions') or ()
		questions = questionbank_question_chooser(context, questions)
		result['questions'] = questions
