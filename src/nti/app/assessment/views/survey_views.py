#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from datetime import datetime

from zope import component
from zope import interface

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import RequiredMissing
from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import inquiry_submissions
from nti.app.assessment.common import can_disclose_inquiry
from nti.app.assessment.common import aggregate_page_inquiry
from nti.app.assessment.common import get_course_from_inquiry
from nti.app.assessment.common import aggregate_course_inquiry
from nti.app.assessment.common import check_submission_version
from nti.app.assessment.common import get_available_for_submission_ending
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import ICourseAggregatedInquiries

from nti.app.assessment.survey import UsersCourseInquiryItemResponse

from nti.app.assessment.views import MessageFactory as _

from nti.app.assessment.views import get_ds2

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.renderers.interfaces import INoHrefInResponse

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQSubmittable
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQInquirySubmission

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.oids import to_external_ntiid_oid

from nti.property.property import Lazy

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
CREATOR = StandardExternalFields.CREATOR
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

def allow_to_disclose_inquiry(context, course, user):
	if not is_course_instructor(course, user):
		if not can_disclose_inquiry(context, course):
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
		poll = component.getUtility(IQPoll, name=submission.inquiryId)
		if len(poll.parts) != len(submission.parts):
			ex = ConstraintNotSatisfied(_("Incorrect submission parts."))
			ex.field = IQPollSubmission['parts']
			raise ex

	def _check_submission_before(self, course):
		beginning = get_available_for_submission_beginning(self.context, course)
		if beginning is not None and datetime.utcnow() < beginning:
			ex = ConstraintNotSatisfied(_("Submitting too early."))
			ex.field = IQSubmittable['available_for_submission_beginning']
			ex.value = beginning
			raise ex

	def _check_submission_ending(self, course):
		ending = get_available_for_submission_ending(self.context, course)
		if ending is not None and datetime.utcnow() > ending:
			ex = ConstraintNotSatisfied(_("Submitting too late."))
			ex.field = IQSubmittable['available_for_submission_ending']
			raise ex

	def _check_inquiry_close(self):
		if self.context.closed:
			ex = ConstraintNotSatisfied(_("Inquiry has been closed."))
			ex.field = IQInquiry['closed']
			raise ex

	def _check_version(self, submission):
		check_submission_version(submission, self.context)

	def _do_call(self):
		course = self.course
		creator = self.remoteUser
		self._check_inquiry_close()
		self._check_submission_before(course)
		self._check_submission_ending(course)

		submission = self.readCreateUpdateContentObject(creator)
		self._check_version(submission)

		# Check that the submission has something for all polls
		if IQSurveySubmission.providedBy(submission):
			survey = component.getUtility(IQSurvey, name=submission.inquiryId)
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
		submission.containerId = submission.inquiryId

		if submission.inquiryId in course_inquiry:
			ex = NotUnique(_("Inquiry already submitted."))
			ex.field = IQInquirySubmission['inquiryId']
			ex.value = submission.inquiryId
			raise ex

		version = self.context.version
		if version is not None:  # record version
			submission.version = version

		# Now record the submission.
		self.request.response.status_int = 201
		recorded = course_inquiry.recordSubmission(submission)
		result = UsersCourseInquiryItemResponse(Submission=recorded)
		if allow_to_disclose_inquiry(self.context, course, self.remoteUser):
			result.Aggregated = aggregate_course_inquiry(self.context, course, recorded)

		result = to_external_object(result)
		result['href'] = "/%s/Objects/%s" % (get_ds2(self.request),
											 to_external_ntiid_oid(recorded))
		interface.alsoProvides(result, INoHrefInResponse)

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
			 context=IQInquiry,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Submissions")
class InquirySubmissionsView(AbstractAuthenticatedView, InquiryViewMixin):

	def __call__(self):
		course = self.course
		if course is None:
			raise hexc.HTTPUnprocessableEntity(_("Course not found."))
		if not (	is_course_instructor(course, self.remoteUser) 
				or	has_permission(nauth.ACT_NTI_ADMIN, course, self.request)):
			raise hexc.HTTPForbidden(_("Cannot get inquiry submissions."))
		result = LocatedExternalDict()
		queried = inquiry_submissions(self.context, course)

		def _key(item):
			lastModified = item.lastModified
			creator = getattr(item.creator, 'username', item.creator)
			return (lastModified, creator or u'')

		def _ext_obj(item):
			result = to_external_object(item, decorate=False)
			result.pop(CREATOR, None)
			result.pop('questions', None)
			return result

		items = result[ITEMS] = [_ext_obj(x.Submission) for x in sorted(queried, key=_key)]
		result['Inquiry'] = to_external_object(self.context, decorate=False)
		result[TOTAL] = result[ITEM_COUNT] = len(items)
		return result

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

@view_config(name='close')
@view_config(name='Close')
@view_defaults(route_name="objects.generic.traversal",
			   context=IQInquiry,
			   renderer='rest',
			   request_method='POST',
			   permission=nauth.ACT_READ)
class InquiryCloseView(AbstractAuthenticatedView, InquiryViewMixin):

	def __call__(self):
		course = self.course
		if not is_course_instructor(course, self.remoteUser):
			raise hexc.HTTPForbidden(_("Cannot close inquiry."))
		self.context.closed = True
		result = aggregate_course_inquiry(self.context, course)
		container = ICourseAggregatedInquiries(course)
		container[self.context.ntiid] = result
		return result

@view_config(name='open')
@view_config(name='Open')
@view_defaults(route_name="objects.generic.traversal",
			   context=IQInquiry,
			   renderer='rest',
			   request_method='POST',
			   permission=nauth.ACT_READ)
class InquiryOpenView(AbstractAuthenticatedView, InquiryViewMixin):

	def __call__(self):
		course = self.course
		if not is_course_instructor(course, self.remoteUser):
			raise hexc.HTTPForbidden(_("Cannot open inquiry."))
		self.context.closed = False
		try:
			container = ICourseAggregatedInquiries(course)
			del container[self.context.ntiid]
		except KeyError:
			pass
		return hexc.HTTPNoContent()

@view_config(route_name="objects.generic.traversal",
			 context=IQInquiry,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Aggregated")
class InquiryAggregatedGetView(AbstractAuthenticatedView, InquiryViewMixin):

	def __call__(self):
		course = self.course
		if not allow_to_disclose_inquiry(self.context, course, self.remoteUser):
			raise hexc.HTTPForbidden(_("Cannot disclose inquiry results."))
		if self.context.closed:
			container = ICourseAggregatedInquiries(course)
			result = container[self.context.ntiid]
		else:
			result = aggregate_course_inquiry(self.context, course)
		if result is None:
			return hexc.HTTPNoContent()
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQInquirySubmission,
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 request_method='POST')
class InquirySubmisionPostView(UGDPostView):

	def __call__(self):
		result = super(InquirySubmisionPostView, self).__call__()
		inquiry = component.getUtility(IQInquiry, name=self.context.inquiryId)
		if can_disclose_inquiry(inquiry):
			mimeType = self.context.mimeType
			containerId = self.context.containerId
			result = aggregate_page_inquiry(containerId, mimeType, self.context)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQInquirySubmission,
			 renderer='rest',
			 permission=nauth.ACT_READ,
			 request_method='PUT')
class InquirySubmisionPutView(UGDPutView):

	def __call__(self):
		raise hexc.HTTPForbidden(_("Cannot put an inquiry submission."))
