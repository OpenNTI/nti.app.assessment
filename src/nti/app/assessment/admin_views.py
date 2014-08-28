#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time
from urllib import unquote

from zope import component

from pyramid.view import view_config
from pyramid.view import view_defaults
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.assessment import grader_for_response
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.randomized import shuffle_list
from nti.assessment.interfaces import IQAssessedPart
from nti.assessment.randomized import randomize as randomzier
from nti.assessment.randomized.interfaces import IQRandomizedMultipleChoicePart

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser
from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverFolder

from nti.externalization.interfaces import LocatedExternalDict

from nti.utils.maps import CaseInsensitiveDict

from ._utils import copy_part

from .interfaces import ICourseAssessmentItemCatalog
from .interfaces import IUsersCourseAssignmentHistory

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_MODERATE,
			   request_method='GET',
			   name='AllTasksOutline')
class AllTasksOutlineView(AbstractAuthenticatedView):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		catalog = ICourseAssessmentItemCatalog(instance)

		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		for item in catalog.iter_assessment_items():
			unit = item.__parent__
			result.setdefault(unit.ntiid, []).append(item)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IDataserverFolder,
			 permission=nauth.ACT_MODERATE,
			 name='MultipleChoiceFixer')
class _XXX_HACK_MultipleChoiceFixerView(AbstractAuthenticatedView,
										ModeledContentUploadRequestUtilsMixin):
	
	def readInput(self):
		values = super(_XXX_HACK_MultipleChoiceFixerView, self).readInput()
		result = CaseInsensitiveDict(values)
		return result

	def _shuffle(self, generator, choices, solution):
		original = {idx:v for idx, v in enumerate(choices)}
		shuffled = {v:idx for idx, v in enumerate(shuffle_list(generator, choices))}
		value = int(solution)
		result = shuffled[original[value]]
		return result

	def __call__(self):
		values = self.readInput()
		username = values.get('username') or values.get('user')
		if not username:
			raise hexc.HTTPUnprocessableEntity(detail='No username')

		user = User.get_user(username)
		if not user or not IUser.providedBy(user):
			raise hexc.HTTPUnprocessableEntity(detail='User not found')

		ntiid = values.get('ntiid') or values.get('assignment') or \
				values.get('assignmentId') or values.get('assignment_id')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity(detail='No assignment identifier')
		ntiid = unquote(ntiid)
		assignment =  component.queryUtility(IQAssignment, ntiid)
		if not assignment:
			raise hexc.HTTPUnprocessableEntity(detail='No assignment found')
		
		course = component.queryMultiAdapter((assignment, user), ICourseInstance)
		if not course:
			raise hexc.HTTPUnprocessableEntity(detail='No assignment course found')
		
		entry = ICourseCatalogEntry(course)
		logger.info('Course %s found for user and assignment', entry.ntiid)
		
		assignment_history = component.getMultiAdapter( (course, user),
														IUsersCourseAssignmentHistory )
		history_item = assignment_history.get(ntiid)
		if history_item is None:
			logger.warn('User has not taken assignment')
			raise hexc.HTTPUnprocessableEntity(detail='User has not taken assignment')
				
		result = LocatedExternalDict()
		items = result['Items'] = {}
		submission = history_item.Submission
		
		pending_assessment = history_item.pendingAssessment
		
		submission._p_activate()
		for part_idx, sub_part in enumerate(submission.parts):
			for question_idx, sub_question in enumerate(sub_part.questions):
				# find  question
				question = component.queryUtility(IQuestion, sub_question.questionId)
				if question is None:
					continue
				
				modified = False
				for idx, t in enumerate(zip(question.parts, sub_question.parts)):
					# check part
					part, sub_part = t
					if not IQRandomizedMultipleChoicePart.providedBy(part):
						continue
					
					logger.info("Updating question %s", sub_question.questionId)
					
					response = getattr(sub_part, 'submittedResponse', sub_part)
					logger.info("sha224 response index %s", response)
					
					# get grader
					grader = grader_for_response(part, response)
					
					# unshuffle sha224
					copied = copy_part(part, sha224randomized=True)
					unshuffled = grader.unshuffle(response, user=user, context=copied)
					logger.info("unshuffled response index %s", unshuffled)
					
					# shuffle legacy
					generator = randomzier(user)
					shuffled = self._shuffle(generator, part.choices, unshuffled)
					logger.info("new [legacy] shuffled response index %s", shuffled)
					
					# verify
					assert grader.unshuffle(shuffled, user=user) == unshuffled
					
					# update and register
					if self.request.method != 'GET':
						modified = True
						sub_question.parts[idx] = shuffled
						
						# change assessed question set
						asd_qset = pending_assessment.parts[part_idx]
						asd_question = asd_qset.questions[question_idx]
						asd_part = asd_question.parts[idx]
						if IQAssessedPart.providedBy(asd_part):
							asd_part.submittedResponse = shuffled
							logger.info("QAssessedPart submittedResponse changed to %s", shuffled)
							
					items[sub_question.questionId] = {response:shuffled}
				
				if modified:
					submission._p_changed = True
					submission.updateLastModIfGreater(time.time())
		return result