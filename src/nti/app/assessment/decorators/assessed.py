#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import numbers

from zope import component

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.authentication import get_remote_user

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.common import grader_for_response

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssessedPart
from nti.assessment.interfaces import IQAssessedQuestion
from nti.assessment.interfaces import IQuestionSubmission
from nti.assessment.interfaces import IQPartSolutionsExternalizer

from nti.assessment.randomized.interfaces import IQRandomizedPart

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.utils import is_course_instructor

from nti.externalization.singleton import SingletonDecorator
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object

from nti.links.links import Link

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS

def _question_from_context(context, questionId):
	item = find_interface(context, IUsersCourseAssignmentHistoryItem, strict=False)
	if item is None or item.Assignment is None:
		result = component.queryUtility(IQuestion, name=questionId)
		return result
	else:
		for part in item.Assignment.parts:
			for question in part.question_set.questions:
				if question.ntiid == questionId:
					return question
		return result

@component.adapter(IQAssessedPart)
class _QAssessedPartDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, context, result_map):
		course = find_interface(context, ICourseInstance, strict=False)
		if course is None or not is_course_instructor(course, self.remoteUser):
			return

		# extra check
		uca_history = find_interface(context, IUsersCourseAssignmentHistory, strict=False)
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
		if IQRandomizedPart.providedBy(question_part):
			response = context.submittedResponse
			if response is not None:
				__traceback_info__ = type(response), response, question_part
				grader = grader_for_response(question_part, response)
				assert grader is not None

				# CS: We need the user that submitted the question
				# in order to unshuffle the response
				creator = uca_history.creator
				response = grader.unshuffle(response,
											user=creator,
											context=question_part)
				ext_response = \
					response if isinstance(response, (numbers.Real, basestring)) \
					else to_external_object(response)
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
		uca_history = find_interface(context, IUsersCourseAssignmentHistory, strict=False)
		if uca_history is None or uca_history.creator == self.remoteUser:
			return

		# find question
		question_id = context.questionId
		question = component.queryUtility(IQuestion, name=question_id)
		if question is None:
			return  # old question?

		if len(question.parts) != len(context.parts):
			logger.warn("Not all question parts were submitted")

		# CS: We need the user that submitted the question
		# in order to unshuffle the response
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
					ext_sub_part = 	\
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

	def decorateExternalObject(self, context, mapping):
		question_id = context.questionId
		question = component.queryUtility(IQuestion, name=question_id)
		if question is None:
			return  # old?

		remoteUser = get_remote_user()
		course = find_interface(context, ICourseInstance, strict=False)
		is_instructor = remoteUser and course and is_course_instructor(course, remoteUser)

		for question_part, external_part in zip(question.parts, mapping['parts']):
			if not is_instructor:
				externalizer = IQPartSolutionsExternalizer(question_part)
				external_part['solutions'] = externalizer.to_external_object()
			else:
				external_part['solutions'] = to_external_object(question_part.solutions)
			external_part['explanation'] = to_external_object(question_part.explanation)

class _QAssignmentSubmissionPendingAssessmentDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		creator = getattr(context.__parent__, 'creator', None)
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
				and creator is not None
				and creator == self.remoteUser)

	def _do_decorate_external(self, context, result_map):
		item = find_interface(context, IUsersCourseAssignmentHistoryItem, strict=False)
		if item is not None:
			links = result_map.setdefault(LINKS, [])
			links.append(Link(item, rel='AssignmentHistoryItem'))
