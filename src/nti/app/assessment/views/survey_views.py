#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from . import MessageFactory as _

from datetime import datetime

from zope import component

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import RequiredMissing
from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.utils import is_course_instructor

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQSubmittable
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQInquirySubmission

from nti.common.property import Lazy

from nti.dataserver import authorization as nauth

from ..common import aggregate_inquiry
from ..common import can_disclose_inquiry
from ..common import get_course_from_inquiry
from ..common import get_available_for_submission_ending

from ..interfaces import IUsersCourseInquiry
from ..interfaces import IUsersCourseInquiries
from ..interfaces import IUsersCourseInquiryItem

def allow_to_disclose_inquiry(context, course, user):
	if not is_course_instructor(course, user):
		if not can_disclose_inquiry(context):
			return False
	return True

class InquiryViewMixin(object):

	@Lazy
	def course(self):
		creator = self.remoteUser
		if not creator:
			raise hexc.HTTPForbidden(_("Must be Authenticated."))
		try:
			course = get_course_from_inquiry(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden(_("Must be enrolled in a course."))
			return course
		except RequiredMissing:
			raise hexc.HTTPForbidden(_("Must be enrolled in a course."))

@view_config(route_name="objects.generic.traversal",
			 context=IQInquiry,
			 renderer='rest',
			 request_method='POST',
			 permission=nauth.ACT_READ)
class InquirySubmissionPostView(AbstractAuthenticatedView,
						  		ModeledContentUploadRequestUtilsMixin,
						  		InquiryViewMixin):

	_EXTRA_INPUT_ERRORS = \
			ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + (AttributeError,)

	content_predicate = IQInquirySubmission.providedBy

	def _check_poll_submission(self, submission):
		poll = component.getUtility(IQPoll, name=submission.id)
		if len(poll.parts) != len(submission.parts):
			ex = ConstraintNotSatisfied(_("Incorrect submission parts."))
			ex.field = IQPollSubmission['parts']
			raise ex

	def _do_call(self):
		course = self.course
		creator = self.remoteUser
		ending = get_available_for_submission_ending(course, self.context)
		if datetime.utcnow() > ending:
			ex = ConstraintNotSatisfied(_("Inquiry has been closed."))
			ex.field = IQSubmittable['available_for_submission_ending']
			raise ex

		submission = self.readCreateUpdateContentObject(creator)

		# Check that the submission has something for all polls
		if IQSurveySubmission.providedBy(submission):
			survey = component.getUtility(IQSurvey, name=submission.id)
			survey_poll_ids = [poll.ntiid for poll in survey.questions]
			submission_poll_ids = [poll.pollId for poll in submission.questions]
			if sorted(survey_poll_ids) != sorted(submission_poll_ids):
				ex = ConstraintNotSatisfied(_("Incorrect submission questions."))
				ex.field = IQSurveySubmission['questions']
				raise ex
			for question_sub in submission.questions:
				self._check_poll_submission(question_sub)
		elif IQPollSubmission.providedBy(submission):
			self._check_poll_submission(submission)

		creator = submission.creator
		course_inquiry = component.getMultiAdapter((course, creator), 
												   IUsersCourseInquiry)
		submission.containerId = submission.id

		if submission.id in course_inquiry:
			ex = NotUnique(_("Inquiry already submitted"))
			ex.field = IQInquirySubmission['id']
			ex.value = submission.id
			raise ex

		# Now record the submission.
		self.request.response.status_int = 201
		result = course_inquiry.recordSubmission(submission)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQInquiry,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Submission")
class InquirySubmissionGetView(AbstractAuthenticatedView, InquiryViewMixin):

	def __call__(self):
		course = self.course
		creator = self.remoteUser
		course_inquiry = component.getMultiAdapter((course, creator), 
												   IUsersCourseInquiry)
		try:
			result = course_inquiry[self.context.ntiid]
			return result
		except KeyError:
			return hexc.HTTPNotFound()

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseInquiries,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class InquiriesGetView(AbstractAuthenticatedView):
	"""
	Students can view their survey/polls submissions as ``path/to/course/Inquiries``
	"""

	def __call__(self):
		result = self.request.context
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseInquiryItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class InquiryItemDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject

@view_config(route_name="objects.generic.traversal",
			 context=IQInquiry,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Aggregated")
class AggregatedInquiryGetView(AbstractAuthenticatedView, InquiryViewMixin):

	def __call__(self):
		course = self.course
		if not allow_to_disclose_inquiry(self.context, course, self.remoteUser):
			raise hexc.HTTPForbidden(_("Cannot disclose inquiry results."))
		result = aggregate_inquiry(self.context, course)
		return result
