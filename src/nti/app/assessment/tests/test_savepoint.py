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
from hamcrest import assert_that
from hamcrest import has_property

from nti.app.assessment.savepoint import UsersCourseAssignmentSavepoint
from nti.app.assessment.savepoint import UsersCourseAssignmentSavepointItem

from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepointItem

from nti.assessment.submission import AssignmentSubmission

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser

from nti.testing.matchers import validly_provides

from nti.app.assessment.tests import AssessmentLayerTest

class TestSavepoint(AssessmentLayerTest):

	def test_provides(self):
		savepoint = UsersCourseAssignmentSavepoint()
		savepoint.__parent__ = User('sjohnson@nextthought.com')

		item = UsersCourseAssignmentSavepointItem()
		item.__parent__ = savepoint
		
		assert_that( item, validly_provides(IUsersCourseAssignmentSavepointItem))
		assert_that(item.creator, is_(savepoint.creator))
		
		assert_that( savepoint, validly_provides(IUsersCourseAssignmentSavepoint))
		assert_that( IUser(item), is_(savepoint.owner))
		assert_that( IUser(savepoint), is_(savepoint.owner))

	def test_record(self):
		savepoint = UsersCourseAssignmentSavepoint()
		savepoint.__parent__ = User('sjohnson@nextthought.com')
		
		submission = AssignmentSubmission(assignmentId='b')
		item = savepoint.recordSubmission( submission )
	
		assert_that( item, has_property( 'Submission', is_( submission )))
		assert_that( item, has_property( '__name__', is_( submission.assignmentId)) )
		assert_that( item.__parent__, is_( savepoint ))

import fudge

from nti.assessment.submission import QuestionSetSubmission

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object

from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

class TestSavepointViews(RegisterAssignmentLayerMixin, ApplicationLayerTest):
	
	layer = RegisterAssignmentsForEveryoneLayer
	
	features = ('assignments_for_everyone',)

	default_origin = str('http://janux.ou.edu')
	default_username = 'outest75'

	def _check_submission(self, res):
		assert_that(res.status_int, is_(201))
		assert_that(res.json_body, has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
		assert_that(res.json_body, has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))
		assert_that(res.json_body, has_entry(StandardExternalFields.MIMETYPE, 
											 'application/vnd.nextthought.assessment.userscourseassignmentsavepointitem' ) )

		assert_that(res.json_body, has_key('Submission'))
		assert_that(res.json_body, has_entry('href', is_not(none())))
		
		submission = res.json_body['Submission']
		assert_that(submission, has_key('NTIID'))
		assert_that(submission, has_entry('ContainerId', self.assignment_id ))
		assert_that(submission, has_entry( StandardExternalFields.CREATED_TIME, is_( float ) ) )
		assert_that(submission, has_entry( StandardExternalFields.LAST_MODIFIED, is_( float ) ) )
	
	@WithSharedApplicationMockDS(users=('outest5',),testapp=True,default_authenticate=True)
	@fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
	def test_savepoint(self, fake_active):
		# make it look like the course is in session so notables work
		fake_active.is_callable().returns(True)
		
		# Sends an assignment through the ap	plication by posting to the assignment
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		ext_obj = to_external_object( submission )
		del ext_obj['Class']
		assert_that( ext_obj, has_entry('MimeType', 'application/vnd.nextthought.assessment.assignmentsubmission'))
		
		# Make sure we're enrolled
		self.testapp.post_json( '/dataserver2/users/'+self.default_username+'/Courses/EnrolledCourses',
								'CLC 3403',
								status=201 )

		href = '/dataserver2/Objects/' + self.assignment_id + '/Savepoint'
		self.testapp.get(href, status=404)
		
		res = self.testapp.post_json( href, ext_obj)
		savepoint_item_href = res.json_body['href']
		assert_that(savepoint_item_href, is_not(none()))
		
		self._check_submission(res)
		
		res = self.testapp.get(savepoint_item_href)
		assert_that(res.json_body, has_entry('href', is_not(none())))
		
		res = self.testapp.get(href)
		assert_that(res.json_body, has_entry('href', is_not(none())))
		
		# but they can't get each others
		outest_environ = self._make_extra_environ(username='outest5')
		outest_environ.update( {b'HTTP_ORIGIN': b'http://janux.ou.edu'} )
		self.testapp.get(href,
						 extra_environ=outest_environ,
						 status=403)
		
		# we can delete
		self.testapp.delete(savepoint_item_href, status=204)
		self.testapp.get(savepoint_item_href, status=404)
		
		# Whereupon we can submit again
		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id + '/Savepoint',
									  ext_obj)
		self._check_submission(res)
		
		# and again
		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id + '/Savepoint',
									  ext_obj)
		self._check_submission(res)
