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

from nti.app.assessment.decorators import InstructedCourseDecoratorMixin
from nti.app.assessment.decorators import decorate_assessed_values
from nti.app.assessment.decorators import decorate_qset_solutions

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IAvoidSolutionDecoration
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQuestionSet

from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.externalization.interfaces import IExternalObjectDecorator

from nti.externalization.singleton import Singleton

logger = __import__('logging').getLogger(__name__)


@component.adapter(IQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _NTIQuestionSetCountDecorator(Singleton):

    def decorateExternalObject(self, original, external):
        external.pop('question_count', None)
        question_count = getattr(original, 'draw', None) \
                      or len(original.questions)
        external['question-count'] = str(question_count)


class AbstractQuestionSetSolutionDecorator(AbstractAuthenticatedRequestAwareDecorator,
                                           InstructedCourseDecoratorMixin):

    def _predicate(self, context, unused_result):
        return self._is_authenticated and not IAvoidSolutionDecoration.providedBy(context)

    def _get_course(self, qset):
        auth_userid = self.authenticated_userid
        course = self.get_course(qset, auth_userid, self.request)
        return course

    def _is_instructor(self, course):
        if course is None:
            return False

        return self.is_instructor(course, self.request)


@component.adapter(IQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _QQuestionSetObjectDecorator(AbstractQuestionSetSolutionDecorator):

    def _has_self_assessment_submission(self, qset):
        items = self.remoteUser.getContainer(qset.containerId)

        if items:
            for submission in items.values():
                if getattr(submission, 'questionSetId', None) == qset.ntiid:
                    return True

        return False

    def _do_decorate_external(self, context, mapping):
        is_instructor = self._is_instructor(self._get_course(context))
        if not is_instructor and not self._has_self_assessment_submission(context):
            return

        decorate_qset_solutions(context,
                                mapping,
                                is_instructor=is_instructor)


@component.adapter(IQAssessedQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _QAssessedQuestionSetObjectDecorator(AbstractQuestionSetSolutionDecorator):

    def _is_randomized_qset(self, qset):
        return IRandomizedPartsContainer.providedBy(qset)

    def _question_set(self, context):
        qset_id = context.questionSetId or ''
        return component.queryUtility(IQuestionSet, name=qset_id)

    def _has_self_assessment_submission(self, qset_submission):
        items = self.remoteUser.getContainer(qset_submission.containerId)

        if items:
            return qset_submission.id in items

        return False

    def _do_decorate_external(self, context, mapping):
        qset = self._question_set(context)
        is_instructor = None
        if qset is None or not self._has_self_assessment_submission(context):
            is_instructor = self._is_instructor(self._get_course(qset))
            if not is_instructor:
                return

        for q, ext_q in zip(getattr(context, 'questions', None) or (),
                            mapping.get('questions') or ()):
            decorate_assessed_values(q, ext_q)

        # Solutions for instructors handled by
        # `_QAssessedQuestionExplanationSolutionAdder` in
        # `nti.app.assessment.decorators.assessed`
        if is_instructor is None:
            is_instructor = self._is_instructor(self._get_course(qset))

        if is_instructor:
            return

        is_randomized = self._is_randomized_qset(qset)
        decorate_qset_solutions(qset,
                                mapping,
                                is_randomized=is_randomized,
                                is_instructor=is_instructor)
