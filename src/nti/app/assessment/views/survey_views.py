#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import RequiredMissing
from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQSurveySubmission

from nti.dataserver import authorization as nauth

from ..common import get_course_from_survey

from ..interfaces import IUsersCourseSurvey
from ..interfaces import IUsersCourseSurveys
from ..interfaces import IUsersCourseSurveyItem

@view_config(route_name="objects.generic.traversal",
			 context=IQSurvey,
			 renderer='rest',
			 request_method='POST',
			 permission=nauth.ACT_READ )
class SurveySubmissionPostView(	AbstractAuthenticatedView,
						  		ModeledContentUploadRequestUtilsMixin):

	_EXTRA_INPUT_ERRORS = \
			ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + (AttributeError,)

	content_predicate = IQSurveySubmission.providedBy

	def _do_call(self):
		creator = self.remoteUser
		if not creator:
			raise hexc.HTTPForbidden("Must be Authenticated")
		try:
			course = get_course_from_survey(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")
		
		submission = self.readCreateUpdateContentObject(creator)
		
		# Get the assignment
		survey = component.getUtility(IQSurvey, name=submission.surveyId)
	
		# Check that the submission has something for all parts
		survey_poll_ids = [poll.ntiid for poll in survey.questions]
		submission_poll_ids = [poll.pollId for poll in submission.questions]

		if sorted(survey_poll_ids) != sorted(submission_poll_ids):
			ex = ConstraintNotSatisfied("Incorrect submission questions")
			ex.field = IQSurveySubmission['questions']
			raise ex
	
		creator = submission.creator
		course_survey = component.getMultiAdapter( (course, creator), IUsersCourseSurvey)
		submission.containerId = submission.surveyId
		
		if submission.surveyId in course_survey:
			ex = NotUnique("Survey already submitted")
			ex.field = IQSurveySubmission['surveyId']
			ex.value = submission.surveyId
			raise ex
	
		## Now record the submission.
		self.request.response.status_int = 201
		result = course_survey.recordSubmission(submission)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQSurvey,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,)
class SurveySubmissionGetView(AbstractAuthenticatedView):

	def __call__(self):
		creator = self.remoteUser
		if not creator:
			raise hexc.HTTPForbidden("Must be Authenticated")
		try:
			course = get_course_from_survey(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

		survey = component.getMultiAdapter( (course, creator), IUsersCourseSurvey)
		try:
			result = survey[self.context.ntiid]
			return result
		except KeyError:
			return hexc.HTTPNotFound()

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseSurveys,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class SurveysGetView(AbstractAuthenticatedView):
	"""
	Students can view their assignment save points as ``path/to/course/Surveys``
	"""

	def __call__(self):
		result = self.request.context
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseSurveyItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class SurveyItemDeleteView(UGDDeleteView):

	def _do_delete_object( self, theObject ):
		del theObject.__parent__[theObject.__name__]
		return theObject
