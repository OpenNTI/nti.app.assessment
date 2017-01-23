#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import contains_string

import weakref

from nti.assessment.interfaces import IQSurveySubmission

from nti.app.assessment.survey import UsersCourseInquiry
from nti.app.assessment.survey import UsersCourseInquiries
from nti.app.assessment.survey import UsersCourseInquiryItem

from nti.assessment.survey import QPollSubmission
from nti.assessment.survey import QSurveySubmission

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiryItem

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser

from nti.testing.matchers import validly_provides

from nti.app.assessment.tests import AssessmentLayerTest

class TestSurvey(AssessmentLayerTest):

	def test_provides(self):
		surveys = UsersCourseInquiries()
		survey = UsersCourseInquiry()
		survey.__parent__ = surveys

		survey.owner = weakref.ref(User('sjohnson@nextthought.com'))
		item = UsersCourseInquiryItem()
		item.creator = 'foo'
		item.__parent__ = survey
		assert_that(item, validly_provides(IUsersCourseInquiryItem))

		assert_that(survey, validly_provides(IUsersCourseInquiry))
		assert_that(IUser(item), is_(survey.owner))
		assert_that(IUser(survey), is_(survey.owner))

	def test_record(self):
		course_survey = UsersCourseInquiry()
		submission = QSurveySubmission(surveyId='b', questions=())
		assert_that(submission, validly_provides(IQSurveySubmission))

		item = course_survey.recordSubmission(submission)
		assert_that(item, has_property('Submission', is_(submission)))
		assert_that(item, has_property('__name__', is_(submission.surveyId)))
		assert_that(item.__parent__, is_(course_survey))
		assert_that(course_survey, has_length(1))

		course_survey.removeSubmission(submission)
		assert_that(course_survey, has_length(0))

import fudge
from urllib import unquote

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object

from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

COURSE_NTIID = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

class TestSurveyViews(RegisterAssignmentLayerMixin, ApplicationLayerTest):

	layer = RegisterAssignmentsForEveryoneLayer

	features = ('assignments_for_everyone',)

	default_origin = str('http://janux.ou.edu')
	default_username = 'outest75'

	@WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
	def test_fetching_entire_survey_collection(self):

		outest_environ = self._make_extra_environ(username='outest5')
		outest_environ.update({b'HTTP_ORIGIN': b'http://janux.ou.edu'})

		res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
									  COURSE_NTIID,
									  status=201)

		default_enrollment_savepoints_link = self.require_link_href_with_rel(res.json_body, 'InquiryHistory')
		expected = ('/dataserver2/users/' +
					self.default_username +
					'/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/Inquiries/' +
					self.default_username)
		assert_that(unquote(default_enrollment_savepoints_link),
					 is_(unquote(expected)))

		res = self.testapp.post_json('/dataserver2/users/outest5/Courses/EnrolledCourses',
								COURSE_NTIID,
								status=201,
								extra_environ=outest_environ)

		user2_enrollment_history_link = self.require_link_href_with_rel(res.json_body, 'InquiryHistory')

		# each can fetch his own
		self.testapp.get(default_enrollment_savepoints_link)
		self.testapp.get(user2_enrollment_history_link, extra_environ=outest_environ)

		# but they can't get each others
		self.testapp.get(default_enrollment_savepoints_link,
						 extra_environ=outest_environ,
						 status=403)
		self.testapp.get(user2_enrollment_history_link, status=403)

	def _check_submission(self, res, inquiry=None, containerId=None):
		assert_that(res.status_int, is_(201))
		assert_that(res.json_body, has_key('Submission'))
		assert_that(res.json_body, has_entry('href', is_not(none())))

		submission = res.json_body['Submission']
		assert_that(submission, has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
		assert_that(submission, has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))
		assert_that(submission, has_entry(StandardExternalFields.MIMETYPE,
										 'application/vnd.nextthought.assessment.userscourseinquiryitem'))

		assert_that(submission, has_key('Submission'))
		submission = submission['Submission']
		if containerId:
			assert_that(submission, has_entry('ContainerId', containerId))
		assert_that(submission, has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
		assert_that(submission, has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))

		if inquiry:
			__traceback_info__ = inquiry
			inquiry_res = self.testapp.get(inquiry)
			assert_that(inquiry_res.json_body, has_entry('href', contains_string(unquote(inquiry))))
			assert_that(inquiry_res.json_body, has_entry('Items', has_length(1)))

			items = list(inquiry_res.json_body['Items'].values())
			assert_that(items[0], has_key('href'))
		else:
			self._fetch_user_url('/Courses/EnrolledCourses/CLC3403/Inquiries/' +
								self.default_username, status=404)

	def _test_submission(self, item_id, ext_obj):
		# Make sure we're enrolled
		res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
									  COURSE_NTIID,
									  status=201)

		enrollment_inquiries_link = self.require_link_href_with_rel(res.json_body, 'InquiryHistory')
		course_inquiries_history_link = self.require_link_href_with_rel(res.json_body['CourseInstance'], 'InquiryHistory')
		course_inquiries_link = self.require_link_href_with_rel(res.json_body['CourseInstance'], 'CourseInquiries')
		submission_href = '%s/%s' % (course_inquiries_link, item_id)
		_ = res.json_body['CourseInstance']['href']

		expected = ('/dataserver2/users/' +
					 self.default_username +
					 '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/Inquiries/' +
					 self.default_username)
		assert_that(unquote(enrollment_inquiries_link),
					is_(unquote(expected)))

		expected = ('/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice/Inquiries/' +
					self.default_username)
		assert_that(unquote(course_inquiries_history_link),
					is_(unquote(expected)))

		# Both survey links are equivalent and work; and both are empty before I submit
		for link in course_inquiries_history_link, enrollment_inquiries_link:
			survey_res = self.testapp.get(link)
			assert_that(survey_res.json_body, has_entry('Items', has_length(0)))

		self.testapp.get(submission_href + '/Submission', status=404)

		res = self.testapp.post_json(submission_href, ext_obj)
		survey_item_href = res.json_body['href']
		assert_that(survey_item_href, is_not(none()))

		self._check_submission(res, enrollment_inquiries_link, item_id)

		res = self.testapp.get(survey_item_href)
		assert_that(res.json_body, has_entry('href', is_not(none())))

		res = self.testapp.get(submission_href)
		assert_that(res.json_body, has_entry('href', is_not(none())))
		assert_that(res.json_body, has_entry('submissions', is_(1)))

		# Both survey links are equivalent and work
		for link in course_inquiries_history_link, enrollment_inquiries_link:
			surveys_res = self.testapp.get(link)
			assert_that(surveys_res.json_body, has_entry('Items', has_length(1)))
			assert_that(surveys_res.json_body, has_entry('Items', has_key(item_id)))

		# simply adding get us to an item
		href = surveys_res.json_body['href'] + '/' + item_id
		res = self.testapp.get(href)
		assert_that(res.json_body, has_entry('href', is_not(none())))

		# we cannnot delete
		self.testapp.delete(survey_item_href, status=403)
		self.testapp.get(survey_item_href, status=200)

	@WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
	@fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
	def test_survey(self, fake_active):
		fake_active.is_callable().returns(True)

		poll_sub = QPollSubmission(pollId=self.poll_id, parts=[0])
		submission = QSurveySubmission(surveyId=self.survey_id,
										questions=[poll_sub])

		ext_obj = to_external_object(submission)
		del ext_obj['Class']
		assert_that(ext_obj, has_entry('MimeType', 'application/vnd.nextthought.assessment.surveysubmission'))

		self._test_submission(self.survey_id, ext_obj)

	@WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
	@fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
	def test_poll(self, fake_active):
		fake_active.is_callable().returns(True)

		submission = QPollSubmission(pollId=self.poll_id, parts=[0])

		ext_obj = to_external_object(submission)
		del ext_obj['Class']
		assert_that(ext_obj, has_entry('MimeType', 'application/vnd.nextthought.assessment.pollsubmission'))

		self._test_submission(self.poll_id, ext_obj)
