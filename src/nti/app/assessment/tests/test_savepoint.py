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

from nti.testing.matchers import validly_provides

import weakref

from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepointItem

from nti.app.assessment.savepoint import UsersCourseAssignmentSavepoint
from nti.app.assessment.savepoint import UsersCourseAssignmentSavepoints
from nti.app.assessment.savepoint import UsersCourseAssignmentSavepointItem

from nti.assessment.submission import AssignmentSubmission

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.app.assessment.tests import AssessmentLayerTest

from nti.dataserver.tests import mock_dataserver
from nti.dataserver.tests.mock_dataserver import WithMockDSTrans

COURSE_NTIID = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

class TestSavepoint(AssessmentLayerTest):

	def test_provides(self):
		savepoints = UsersCourseAssignmentSavepoints()
		savepoint = UsersCourseAssignmentSavepoint()
		savepoint.__parent__ = savepoints

		# Set an owner; use a python wref instead of the default
		# adapter to wref as it requires an intid utility
		savepoint.owner = weakref.ref(User('sjohnson@nextthought.com'))
		item = UsersCourseAssignmentSavepointItem()
		item.creator = 'foo'
		item.__parent__ = savepoint
		assert_that(item,
					 validly_provides(IUsersCourseAssignmentSavepointItem))

		assert_that(savepoint,
					 validly_provides(IUsersCourseAssignmentSavepoint))
		assert_that(IUser(item), is_(savepoint.owner))
		assert_that(IUser(savepoint), is_(savepoint.owner))

	@WithMockDSTrans
	def test_record(self):
		connection = mock_dataserver.current_transaction
		for event  in (True, False):
			savepoint = UsersCourseAssignmentSavepoint()
			connection.add(savepoint)
			submission = AssignmentSubmission(assignmentId='b')

			item = savepoint.recordSubmission(submission, event=event)
			assert_that(item, has_property('Submission', is_(submission)))
			assert_that(item, has_property('__name__', is_(submission.assignmentId)))
			assert_that(item.__parent__, is_(savepoint))
			assert_that(savepoint, has_length(1))

			savepoint.removeSubmission(submission, event=event)
			assert_that(savepoint, has_length(0))

import fudge
from urllib import unquote

from nti.assessment.submission import QuestionSetSubmission

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object

from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

class TestSavepointViews(RegisterAssignmentLayerMixin, ApplicationLayerTest):

	layer = RegisterAssignmentsForEveryoneLayer

	features = ('assignments_for_everyone',)

	default_origin = str('http://janux.ou.edu')
	default_username = 'outest75'

	@WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
	def test_fetching_entire_assignment_savepoint_collection(self):

		outest_environ = self._make_extra_environ(username='outest5')
		outest_environ.update({b'HTTP_ORIGIN': b'http://janux.ou.edu'})

		res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
									 COURSE_NTIID,
									 status=201)

		default_enrollment_savepoints_link = self.require_link_href_with_rel(res.json_body, 'AssignmentSavepoints')
		expected = ('/dataserver2/users/' +
					self.default_username +
					'/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/AssignmentSavepoints/' + 
					self.default_username)
		assert_that(unquote(default_enrollment_savepoints_link), is_(unquote(expected)))

		res = self.testapp.post_json(
							'/dataserver2/users/outest5/Courses/EnrolledCourses',
							COURSE_NTIID,
							status=201,
							extra_environ=outest_environ)

		user2_enrollment_history_link = self.require_link_href_with_rel(res.json_body, 'AssignmentSavepoints')

		# each can fetch his own
		self.testapp.get(default_enrollment_savepoints_link)
		self.testapp.get(user2_enrollment_history_link, extra_environ=outest_environ)

		# but they can't get each others
		self.testapp.get(default_enrollment_savepoints_link,
						 extra_environ=outest_environ,
						 status=403)
		self.testapp.get(user2_enrollment_history_link, status=403)

	def _check_submission(self, res, savepoint=None):
		assert_that(res.status_int, is_(201))
		assert_that(res.json_body, has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
		assert_that(res.json_body, has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))
		assert_that(res.json_body, has_entry(StandardExternalFields.MIMETYPE,
											 'application/vnd.nextthought.assessment.userscourseassignmentsavepointitem'))

		assert_that(res.json_body, has_key('Submission'))
		assert_that(res.json_body, has_entry('href', is_not(none())))

		submission = res.json_body['Submission']
		assert_that(submission, has_key('NTIID'))
		assert_that(submission, has_entry('ContainerId', self.assignment_id))
		assert_that(submission, has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
		assert_that(submission, has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))

		# This object can be found in my savepoints
		if savepoint:
			__traceback_info__ = savepoint
			savepoint_res = self.testapp.get(savepoint)
			assert_that(savepoint_res.json_body, has_entry('href', contains_string(unquote(savepoint))))
			assert_that(savepoint_res.json_body, has_entry('Items', has_length(1)))

			items = list(savepoint_res.json_body['Items'].values())
			assert_that(items[0], has_key('href'))
		else:
			self._fetch_user_url('/Courses/EnrolledCourses/CLC3403/AssignmentSavepoints/' +
								self.default_username, status=404)

	@WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
	@fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
	def test_savepoint(self, fake_active):
		fake_active.is_callable().returns(True)

		# Sends an assignment through the application by posting to the assignment
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		ext_obj = to_external_object(submission)
		del ext_obj['Class']
		assert_that(ext_obj, has_entry('MimeType', 'application/vnd.nextthought.assessment.assignmentsubmission'))

		# Make sure we're enrolled
		res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
									 COURSE_NTIID,
									 status=201)

		enrollment_savepoints_link = self.require_link_href_with_rel(res.json_body, 'AssignmentSavepoints')
		course_savepoints_link = self.require_link_href_with_rel(res.json_body['CourseInstance'], 'AssignmentSavepoints')

		expected = ('/dataserver2/users/' +
					self.default_username +
					'/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/AssignmentSavepoints/' +
					self.default_username)
		assert_that(unquote(enrollment_savepoints_link),
					is_(unquote(expected)))

		expected = ('/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice/AssignmentSavepoints/' +
					self.default_username)
		assert_that(unquote(course_savepoints_link),
					is_(unquote(expected)))

		# Both savepoint links are equivalent and work; and both are empty before I submit
		for link in course_savepoints_link, enrollment_savepoints_link:
			savepoints_res = self.testapp.get(link)
			assert_that(savepoints_res.json_body, has_entry('Items', has_length(0)))

		href = '/dataserver2/Objects/' + self.assignment_id + '/Savepoint'
		self.testapp.get(href, status=404)

		res = self.testapp.post_json(href, ext_obj)
		savepoint_item_href = res.json_body['href']
		assert_that(savepoint_item_href, is_not(none()))

		self._check_submission(res, enrollment_savepoints_link)

		res = self.testapp.get(savepoint_item_href)
		assert_that(res.json_body, has_entry('href', is_not(none())))

		res = self.testapp.get(href)
		assert_that(res.json_body, has_entry('href', is_not(none())))

		# Both savepoint links are equivalent and work
		for link in course_savepoints_link, enrollment_savepoints_link:
			savepoints_res = self.testapp.get(link)
			assert_that(savepoints_res.json_body, has_entry('Items', has_length(1)))
			assert_that(savepoints_res.json_body, has_entry('Items', has_key(self.assignment_id)))

		# simply adding get us to an item
		href = savepoints_res.json_body['href'] + '/' + self.assignment_id
		res = self.testapp.get(href)
		assert_that(res.json_body, has_entry('href', is_not(none())))

		# we can delete
		self.testapp.delete(savepoint_item_href, status=204)
		self.testapp.get(savepoint_item_href, status=403)

		# Whereupon we can submit again
		res = self.testapp.post_json('/dataserver2/Objects/' + self.assignment_id + '/Savepoint',
									  ext_obj)
		self._check_submission(res, enrollment_savepoints_link)

		# and again
		res = self.testapp.post_json('/dataserver2/Objects/' + self.assignment_id + '/Savepoint',
									  ext_obj)
		self._check_submission(res, enrollment_savepoints_link)
