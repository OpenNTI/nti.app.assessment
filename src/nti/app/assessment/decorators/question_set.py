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
from nti.app.assessment.decorators import decorate_qset_solutions

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IAvoidSolutionDecoration
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQuestionSet

from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.interfaces import IExternalObjectDecorator

from nti.externalization.singleton import Singleton

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


@component.adapter(IQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _NTIQuestionSetCountDecorator(Singleton):

    def decorateExternalObject(self, original, external):
        external.pop('question_count', None)
        question_count = getattr(original, 'draw', None) \
                      or len(original.questions)
        external['question-count'] = str(question_count)


class QuestionSetDecorationMixin(object):

    def _has_self_assessment_submission(self, qset):
        items = self.remoteUser.getContainer(qset.containerId)

        if items:
            for submission in items.values():
                if getattr(submission, 'questionSetId', None) == qset.ntiid:
                    return True

        return False


@component.adapter(IQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _QQuestionSetObjectDecorator(AbstractAuthenticatedRequestAwareDecorator,
                                   InstructedCourseDecoratorMixin,
                                   QuestionSetDecorationMixin):

    def _predicate(self, context, unused_result):
        return not IAvoidSolutionDecoration.providedBy(context)

    def _do_decorate_external(self, context, mapping):
        has_submission = self._has_self_assessment_submission(context)
        auth_userid = self.authenticated_userid
        course = self._get_course(context, auth_userid, self.request)

        is_instructor = False
        if course is not None:
            is_instructor = self.is_instructor(course, self.request)

        if not has_submission and not is_instructor:
            return

        decorate_qset_solutions(context,
                                mapping,
                                is_instructor=is_instructor)


@component.adapter(IQAssessedQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _QAssessedQuestionSetObjectDecorator(AbstractAuthenticatedRequestAwareDecorator,
                                           InstructedCourseDecoratorMixin,
                                           QuestionSetDecorationMixin):

    def _predicate(self, context, unused_result):
        return not IAvoidSolutionDecoration.providedBy(context)

    def _is_randomized_qset(self, qset):
        return IRandomizedPartsContainer.providedBy(qset)

    def _question_set(self, context):
        qset_id = context.questionSetId or ''
        return component.queryUtility(IQuestionSet, name=qset_id)

    def _do_decorate_external(self, context, mapping):
        qset = self._question_set(context)

        if qset is None:
            return

        auth_userid = self.authenticated_userid
        course = self._get_course(qset, auth_userid, self.request)

        is_instructor = False
        if course is not None:
            is_instructor = self.is_instructor(course, self.request)

        if is_instructor or not self._has_self_assessment_submission(qset):
            return

        is_randomized = self._is_randomized_qset(qset)
        decorate_qset_solutions(qset,
                                mapping,
                                is_randomized=is_randomized,
                                is_instructor=is_instructor)
