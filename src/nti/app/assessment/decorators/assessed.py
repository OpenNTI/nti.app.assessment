#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import numbers

from zope import component

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.authentication import get_remote_user

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.common import grader_for_response

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssessedPart
from nti.assessment.interfaces import IQAssessedQuestion
from nti.assessment.interfaces import IQuestionSubmission
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQPartSolutionsExternalizer

from nti.assessment.randomized.interfaces import IQRandomizedPart
from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor
from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.singleton import SingletonDecorator

from nti.links.links import Link

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS


def _question_from_context(context, questionId):
    item = find_interface(context,
                          IUsersCourseAssignmentHistoryItem,
                          strict=False)
    if item is None or item.Assignment is None:
        result = component.queryUtility(IQuestion, name=questionId)
        return result
    else:
        for part in item.Assignment.parts:
            for question in part.question_set.questions:
                if question.ntiid == questionId:
                    return question
        return result


def _is_instructor_or_editor(course, user):
    return  (user is not None and course is not None) \
        and (   is_course_instructor_or_editor(course, user)
             or has_permission(ACT_CONTENT_EDIT, course))


def _is_randomized_question_set(context):
    """
    See if our contextual submission is a randomized parts container. If so
    we need to shuffle our solutions.
    """
    result = False
    assessed_qset = find_interface(context,
                                   IQAssessedQuestionSet,
                                   strict=False)
    if assessed_qset is not None:
        qset = find_object_with_ntiid(assessed_qset.questionSetId)
        if qset is not None:
            result = IRandomizedPartsContainer.providedBy(qset)
    return result


@component.adapter(IQAssessedPart)
class _QAssessedPartDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _do_decorate_external(self, context, result_map):
        course = find_interface(context, ICourseInstance, strict=False)
        if course is None or not is_course_instructor(course, self.remoteUser):
            return
        # extra check
        uca_history = find_interface(context,
                                     IUsersCourseAssignmentHistory,
                                     strict=False)
        if uca_history is None or uca_history.creator == self.remoteUser:
            return
        # find question
        assessed_question = context.__parent__
        question_id = assessed_question.questionId
        question = component.queryUtility(IQuestion, name=question_id)
        if question is None:
            return  # old question?
        # find part
        try:
            index = assessed_question.parts.index(context)
            question_part = question.parts[index]
        except IndexError:
            return
        # CS: for instructors we no longer randomized the questions
        # since the submittedResponse is stored randomized
        # we unshuffle it, so the instructor can see the correct answer
        if     IQRandomizedPart.providedBy(question_part) \
            or _is_randomized_question_set(context):
            response = context.submittedResponse
            if response is not None:
                __traceback_info__ = type(response), response, question_part
                grader = grader_for_response(question_part, response)
                if grader is None:
                    return
                # CS: We need the user that submitted the question
                # in order to unshuffle the response
                creator = uca_history.creator
                response = grader.unshuffle(response,
                                            user=creator,
                                            context=question_part)
                if isinstance(response, (numbers.Real, basestring)):
                    ext_response = response
                else:
                    ext_response = to_external_object(response)
            else:
                ext_response = response
            result_map['submittedResponse'] = ext_response


@component.adapter(IQuestionSubmission)
class _QuestionSubmissionDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _do_decorate_external(self, context, result_map):
        course = find_interface(context, ICourseInstance, strict=False)
        if course is None or not is_course_instructor(course, self.remoteUser):
            return

        # extra check
        uca_history = find_interface(context,
                                     IUsersCourseAssignmentHistory,
                                     strict=False)
        if uca_history is None or uca_history.creator == self.remoteUser:
            return

        # find question
        question_id = context.questionId
        question = component.queryUtility(IQuestion, name=question_id)
        if question is None:
            return  # old question?

        if len(question.parts) != len(context.parts):
            logger.warn("Not all question parts were submitted")

        # CS: We need the user that submitted the question in
        # order to unshuffle the response
        creator = uca_history.creator
        parts = result_map['parts'] = []
        for question_part, sub_part in zip(question.parts, context.parts):
            # for instructors we no longer randomized the questions
            # since the submitted response is stored randomized
            # we unshuffle it, so the instructor can see the correct answer
            if not IQRandomizedPart.providedBy(question_part):
                parts.append(to_external_object(sub_part))
            else:
                response = ext_sub_part = sub_part
                if sub_part is not None:
                    __traceback_info__ = sub_part, question_part
                    grader = grader_for_response(question_part, sub_part)
                    if grader is not None:
                        response = grader.unshuffle(sub_part,
                                                    user=creator,
                                                    context=question_part)
                    else:
                        logger.warn("Part %s does not correspond submission %s",
                                    question_part, sub_part)
                    ext_sub_part =  \
                        response if isinstance(response, (numbers.Real, basestring)) \
                        else to_external_object(response)
                parts.append(ext_sub_part)


@component.adapter(IQAssessedQuestion)
class _QAssessedQuestionExplanationSolutionAdder(object):
    """
    Because we don't generally want to provide solutions and explanations
    until after a student has submitted, we place them on the assessed object.

    .. note:: In the future this may be registered/unregistered on a site
            by site basis (where a Course is a site) so that instructor preferences
            on whether or not to provide solutions can be respected.
    """

    __metaclass__ = SingletonDecorator

    def _get_externalizer(self, question_part, is_randomized_qset):
        externalizer = None
        if is_randomized_qset or IQRandomizedPart.providedBy(question_part):
            # Look for named random adapter first, if necessary.
            externalizer = component.queryAdapter(question_part,
                                                  IQPartSolutionsExternalizer,
                                                  name="random")
        if externalizer is None:
            # For non-random parts, and actual random part types.
            externalizer = IQPartSolutionsExternalizer(question_part)
        return externalizer

    def decorateExternalObject(self, context, mapping):
        question_id = context.questionId or ''
        question = component.queryUtility(IQuestion, name=question_id)
        if question is None:
            return  # old?

        remoteUser = get_remote_user()
        course = find_interface(context, ICourseInstance, strict=False)
        is_instructor = _is_instructor_or_editor(course, remoteUser)
        is_randomized_qset = _is_randomized_question_set(context)

        for question_part, external_part in zip(question.parts, mapping['parts']):
            if not is_instructor:
                externalizer = self._get_externalizer(question_part,
                                                      is_randomized_qset)
                external_part['solutions'] = externalizer.to_external_object()
            else:
                # Instructors/editors get non-randomized solutions.
                sols = question_part.solutions
                external_part['solutions'] = to_external_object(sols)
            expl = question_part.explanation
            external_part['explanation'] = to_external_object(expl)


class _QAssignmentSubmissionPendingAssessmentDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, result):
        creator = getattr(context.__parent__, 'creator', None)
        return (    AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
                and creator is not None
                and creator == self.remoteUser)

    def _do_decorate_external(self, context, result_map):
        item = find_interface(context,
                              IUsersCourseAssignmentHistoryItem,
                              strict=False)
        if item is not None:
            links = result_map.setdefault(LINKS, [])
            links.append(Link(item, rel='AssignmentHistoryItem'))
