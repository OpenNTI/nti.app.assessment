#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from nti.app.assessment.decorators import _get_course_from_evaluation

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQMatchingPart
from nti.assessment.interfaces import IQOrderingPart
from nti.assessment.interfaces import IQMultipleChoicePart
from nti.assessment.interfaces import IQMultipleChoiceMultipleAnswerPart

from nti.assessment.randomized import randomize
from nti.assessment.randomized import shuffle_list
from nti.assessment.randomized import questionbank_question_chooser
from nti.assessment.randomized import shuffle_matching_part_solutions
from nti.assessment.randomized import shuffle_multiple_choice_part_solutions
from nti.assessment.randomized import shuffle_multiple_choice_multiple_answer_part_solutions

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IQRandomizedPart
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet

from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import IExternalObjectDecorator

logger = __import__('logging').getLogger(__name__)


# pylint: disable=abstract-method
class _AbstractNonEditorRandomizingDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    An abstract decorator that only randomizes if we do not have an instructor or
    an editor, and a non-randomized interface.
    """

    def _predicate(self, context, unused_result):
        user = self.remoteUser
        course = _get_course_from_evaluation(context, user,
                                             request=self.request)
        # XXX: Not sure this is what we want here, regarding the meta attempt
        # We cannot randomize correctly without it; a better solution might be
        # to never return questions/parts for assignments for non-editors
        # without a meta attempt item.
        return  self._is_authenticated \
            and not is_course_instructor_or_editor(course, user) \
            and not has_permission(ACT_CONTENT_EDIT, context, self.request)


# pylint: disable=abstract-method
class _AbstractNonEditorRandomizingPartDecorator(_AbstractNonEditorRandomizingDecorator):
    """
    An abstract decorator that only randomizes if we have a randomized part.
    """

    def _predicate(self, context, result):
        return  IQRandomizedPart.providedBy(context) \
            and super(_AbstractNonEditorRandomizingPartDecorator, self)._predicate(context, result)


@component.adapter(IQMatchingPart)
@interface.implementer(IExternalObjectDecorator)
class _QRandomizedMatchingPartDecorator(_AbstractNonEditorRandomizingPartDecorator):

    def _do_decorate_external(self, context, result):
        generator = randomize(context=context)
        if generator is not None:
            values = list(result['values'])
            shuffle_list(generator, result['values'])
            shuffle_matching_part_solutions(randomize(context=context),  # new generator
                                            values,
                                            result['solutions'])


@component.adapter(IQOrderingPart)
@interface.implementer(IExternalObjectDecorator)
class _QRandomizedOrderingPartDecorator(_QRandomizedMatchingPartDecorator):
    pass


@interface.implementer(IExternalObjectDecorator)
@component.adapter(IQMultipleChoicePart)
class _QRandomizedMultipleChoicePartDecorator(_AbstractNonEditorRandomizingPartDecorator):

    def _predicate(self, context, result):
        # Cannot handle these types of IQMultipleChoiceParts
        # Should this implement IQMultipleChoicePart then?
        return not IQMultipleChoiceMultipleAnswerPart.providedBy(context) \
           and super(_QRandomizedMultipleChoicePartDecorator, self)._predicate(context, result)

    def _do_decorate_external(self, context, result):
        generator = randomize(context=context)
        if generator is not None:
            solutions = result['solutions']
            choices = list(result['choices'])
            shuffle_list(generator, result['choices'])
            shuffle_multiple_choice_part_solutions(randomize(context=context),  # new generator
                                                   choices,
                                                   solutions)


@interface.implementer(IExternalObjectDecorator)
@component.adapter(IQMultipleChoiceMultipleAnswerPart)
class _QRandomizedMultipleChoiceMultipleAnswerPartDecorator(_AbstractNonEditorRandomizingPartDecorator):

    def _do_decorate_external(self, context, result):
        generator = randomize(context=context)
        if generator is not None:
            choices = list(result['choices'])
            shuffle_list(generator, result['choices'])
            shuffle_multiple_choice_multiple_answer_part_solutions(randomize(context=context),  # new generator
                                                                   choices,
                                                                   result['solutions'])


@component.adapter(IRandomizedQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _QRandomizedQuestionSetDecorator(_AbstractNonEditorRandomizingDecorator):

    def _do_decorate_external(self, context, result):
        generator = randomize(context=context)
        questions = result.get('questions', ())
        # XXX: How do we get a non-empty tuple here?
        result['questions'] = questions = list(questions)
        if generator and questions:
            shuffle_list(generator, questions)


@component.adapter(IQuestionBank)
@interface.implementer(IExternalObjectDecorator)
class _QQuestionBankDecorator(_AbstractNonEditorRandomizingDecorator):

    def _do_decorate_external(self, context, result):
        questions = result.get('questions') or ()
        questions = questionbank_question_chooser(context, questions)
        result['questions'] = questions
