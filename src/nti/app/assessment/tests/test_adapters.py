#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""


$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

#disable: accessing protected members, too many methods
#pylint: disable=W0212,R0904


from hamcrest import assert_that
from hamcrest import is_
from hamcrest import has_length
from hamcrest import has_item
from hamcrest import has_entry
from hamcrest import has_key
from hamcrest import contains_string
from hamcrest import ends_with
from hamcrest import has_property
from hamcrest import contains
from hamcrest import calling
from hamcrest import raises
from hamcrest import has_entries

from nti.dataserver.tests import mock_dataserver
from nti.testing.matchers import validly_provides

import os
from zope import component
import datetime

from nti.app.testing.application_webtest import SharedApplicationTestBase
from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.filesystem import CachedNotifyingStaticFilesystemLibrary as Library

from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import StandardExternalFields

from nti.dataserver.users import User

from nti.app.products.courseware.tests import test_catalog_from_content

from nti.assessment.assignment import QAssignmentPart, QAssignment
from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission
from nti.assessment import interfaces as asm_interfaces
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment
from nti.assessment.interfaces import IQAssessmentItemContainer

from ..adapters import _begin_assessment_for_assignment_submission
from ..feedback import UsersCourseAssignmentHistoryItemFeedback

from urllib import unquote

class TestAssignmentGrading(SharedApplicationTestBase):


	@classmethod
	def _setup_library( cls, *args, **kwargs ):
		return Library(
					paths=(
						   os.path.join(
								   os.path.dirname(test_catalog_from_content.__file__),
								   'Library',
								   'CLC3403_LawAndJustice'),))

	@classmethod
	def setUpClass(cls):
		super(TestAssignmentGrading,cls).setUpClass()

		question_set_id  = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
		assignment_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle"

		lib = component.getUtility(IContentPackageLibrary)

		clc = lib.contentPackages[0]

		question_set = component.getUtility(asm_interfaces.IQuestionSet,
											name=question_set_id)

		assignment_part = QAssignmentPart(question_set=question_set)
		assignment = QAssignment( parts=(assignment_part,) )
		assignment.__name__ = assignment.ntiid = assignment_ntiid

		component.provideUtility( assignment,
								  provides=asm_interfaces.IQAssignment,
								  name=assignment_ntiid )

		# Also make sure this assignment is found in the assignment index
		# at some container
		lesson_page_id = "tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:02.01_RequiredReading"
		lesson = lib.pathToNTIID(lesson_page_id)[-1]
		assignment.__parent__ = lesson
		IQAssessmentItemContainer(lesson).append(assignment)

		cls.question_set = question_set
		cls.assignment = assignment
		cls.question_set_id = question_set_id
		cls.assignment_id = assignment_ntiid
		cls.lesson_page_id = lesson_page_id

	@WithSharedApplicationMockDS
	def test_wrong_id(self):
		submission = AssignmentSubmission(assignmentId='b')
		# A component lookup error for the assignment using adapter syntax
		# turns into a TypeError
		assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
					 raises(TypeError))

		assert_that( calling(_begin_assessment_for_assignment_submission).with_args(submission),
					 raises(LookupError))


	@WithSharedApplicationMockDS
	def test_wrong_parts(self):
		submission = AssignmentSubmission(assignmentId=self.assignment_id)

		assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
					 raises(ValueError, 'parts') )

	@WithSharedApplicationMockDS
	def test_before_open(self):
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		# Open tomorrow
		self.assignment.available_for_submission_beginning = (datetime.datetime.now() + datetime.timedelta(days=1))
		try:
			assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
						 raises(ValueError, 'early') )
		finally:
			self.assignment.available_for_submission_beginning = None


	@WithSharedApplicationMockDS(users=True)
	def test_pending(self):
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		with mock_dataserver.mock_db_trans(self.ds):
			# No creator
			assert_that( calling( IQAssignmentSubmissionPendingAssessment ).with_args(submission),
						 raises( TypeError ))

			user = User.get_user( self.extra_environ_default_user )
			submission.creator = user
			pending = IQAssignmentSubmissionPendingAssessment(submission)
			assert_that( pending, validly_provides(IQAssignmentSubmissionPendingAssessment))
			assert_that( pending.parts, contains(qs_submission))

		# If we try again, we fail
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))
		with mock_dataserver.mock_db_trans(self.ds):

			user = User.get_user( self.extra_environ_default_user )
			submission.creator = user
			assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
						 raises(ValueError, 'already submitted') )

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_pending_application_user_data(self):
		# Sends an assignment through the application by sending it to the user.
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		ext_obj = to_external_object( submission )
		# If these are posted to the user, they should have a container ID,
		# but because we are not storing them on the user, it doesn't matter...
		# it gets replacen anyway
		# to anything)
		ext_obj['ContainerId'] = 'tag:nextthought.com,2011-10:mathcounts-HTML-MN.2012.0'

		res = self.post_user_data( ext_obj )

		self._check_submission(res)

	def _check_submission(self, res, history=None):
		assert_that( res.status_int, is_( 201 ))
		assert_that( res.json_body, has_entry( StandardExternalFields.CREATED_TIME, is_( float ) ) )
		assert_that( res.json_body, has_entry( StandardExternalFields.LAST_MODIFIED, is_( float ) ) )
		assert_that( res.json_body, has_entry( StandardExternalFields.MIMETYPE, 'application/vnd.nextthought.assessment.assignmentsubmissionpendingassessment' ) )

		assert_that( res.json_body, has_entry( 'ContainerId', self.assignment_id ))
		assert_that( res.json_body, has_key( 'NTIID' ) )

		assert_that( res, has_property( 'location', contains_string('Objects/')))

		# This object can be found in my history
		if history:
			__traceback_info__ = history
			res = self.testapp.get(history)
			assert_that( res.json_body, has_entry('href', contains_string(unquote(history)) ) )
			assert_that( res.json_body, has_entry('Items', has_length(1)))
			assert_that( res.json_body, has_entry('lastViewed', 0))
		else:
			# Because we're not enrolled...actually, we shouldn't
			# have been able to submit...this is here to make sure something
			# breaks when acls change
			res = self._fetch_user_url( '/Courses/EnrolledCourses/CLC3403/AssignmentHistory', status=404 )

		return res

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_pending_application_assignment(self):
		# Sends an assignment through the application by posting to the assignment
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		ext_obj = to_external_object( submission )
		del ext_obj['Class']
		assert_that( ext_obj, has_entry( 'MimeType', 'application/vnd.nextthought.assessment.assignmentsubmission'))
		# Make sure we're enrolled
		res = self.testapp.post_json( '/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses',
									  'CLC 3403',
									  status=201 )
		enrollment_history_link = self.require_link_href_with_rel( res.json_body, 'AssignmentHistory')
		course_history_link = self.require_link_href_with_rel( res.json_body['CourseInstance'], 'AssignmentHistory')

		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id,
									  ext_obj)
		self._check_submission(res, enrollment_history_link)

		history_res = self._check_submission( res, course_history_link )
		__traceback_info__ = history_res.json_body
		history_feedback_container_href = history_res.json_body['Items'].items()[0][1]['Feedback']['href']

		feedback = UsersCourseAssignmentHistoryItemFeedback(body=['Some feedback'])
		ext_feedback = to_external_object(feedback)
		__traceback_info__ = ext_feedback
		res = self.testapp.post_json( history_feedback_container_href,
									  ext_feedback,
									  status=201 )

		history_res = self.testapp.get(course_history_link)
		feedback = history_res.json_body['Items'].items()[0][1]['Feedback']
		assert_that( feedback, has_entry('Items', has_length(1)))
		assert_that( feedback['Items'], has_item( has_entry( 'body', ['Some feedback'])))
		assert_that( feedback['Items'], has_item( has_entry( 'href', ends_with('Feedback/0') ) ) )

		# We can modify the view date by putting to the field
		last_viewed_href = course_history_link + '/lastViewed'
		res = self.testapp.put_json(last_viewed_href, 1234)
		history_res = self.testapp.get(course_history_link)
		assert_that(history_res.json_body, has_entry('lastViewed', 1234))

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_assignment_items_view(self):
		# Make sure we're enrolled
		res = self.testapp.post_json( '/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses',
									  'CLC 3403',
									  status=201 )
		enrollment_assignments = self.require_link_href_with_rel( res.json_body, 'AssignmentsByOutlineNode')
		self.require_link_href_with_rel( res.json_body['CourseInstance'], 'AssignmentsByOutlineNode')

		res = self.testapp.get(enrollment_assignments)
		assert_that( res.json_body, has_entry(self.lesson_page_id,
											  contains( has_entries( 'Class', 'Assignment',
																	 'NTIID', self.assignment.__name__ ))))


class TestAssignmentFileGrading(SharedApplicationTestBase):

	@classmethod
	def _setup_library( cls, *args, **kwargs ):
		return Library(
					paths=(
						   os.path.join(
								   os.path.dirname(test_catalog_from_content.__file__),
								   'Library',
								   'CLC3403_LawAndJustice'),))

	@classmethod
	def setUpClass(cls):
		super(TestAssignmentFileGrading,cls).setUpClass()

		question_set_id  = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
		assignment_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle"
		cls.question_set_id = question_set_id
		cls.assignment_id = assignment_ntiid

		from nti.assessment import parts
		from nti.assessment import response
		from nti.assessment import submission
		from nti.assessment.question import QQuestion
		from nti.assessment.question import QQuestionSet
		from nti.assessment.interfaces import IQuestion
		from nti.assessment.interfaces import IQuestionSet

		lib = component.getUtility(IContentPackageLibrary)


		part = parts.QFilePart()
		part.allowed_mime_types = ('*/*',)
		part.allowed_extensions = '*'
		question = QQuestion( parts=[part] )

		component.provideUtility( question, provides=IQuestion,  name="1")

		question_set = QQuestionSet(questions=(question,))
		question_set.ntiid = cls.question_set_id
		component.provideUtility( question_set, provides=IQuestionSet, name=cls.question_set_id)

		# Works with auto_grade true or false.
		assignment_part = QAssignmentPart(question_set=question_set, auto_grade=False)
		assignment = QAssignment( parts=(assignment_part,) )
		assignment.__name__ = assignment.ntiid = cls.assignment_id

		component.provideUtility( assignment,
								  provides=asm_interfaces.IQAssignment,
								  name=cls.assignment_id )


		# Also make sure this assignment is found in the assignment index
		# at some container
		lesson_page_id = "tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:02.01_RequiredReading"
		lesson = lib.pathToNTIID(lesson_page_id)[-1]
		assignment.__parent__ = lesson
		IQAssessmentItemContainer(lesson).append(assignment)

	def _check_submission(self, res, history=None):
		assert_that( res.status_int, is_( 201 ))
		assert_that( res.json_body, has_entry( StandardExternalFields.CREATED_TIME, is_( float ) ) )
		assert_that( res.json_body, has_entry( StandardExternalFields.LAST_MODIFIED, is_( float ) ) )
		assert_that( res.json_body, has_entry( StandardExternalFields.MIMETYPE, 'application/vnd.nextthought.assessment.assignmentsubmissionpendingassessment' ) )

		assert_that( res.json_body, has_entry( 'ContainerId', self.assignment_id ))
		assert_that( res.json_body, has_key( 'NTIID' ) )

		assert_that( res, has_property( 'location', contains_string('Objects/')))

		# This object can be found in my history
		if history:
			__traceback_info__ = history
			res = self.testapp.get(history)
			assert_that( res.json_body, has_entry('href', contains_string(unquote(history)) ) )
			assert_that( res.json_body, has_entry('Items', has_length(1)))
			assert_that( res.json_body, has_entry('lastViewed', 0))
		else:
			# Because we're not enrolled...actually, we shouldn't
			# have been able to submit...this is here to make sure something
			# breaks when acls change
			res = self._fetch_user_url( '/Courses/EnrolledCourses/CLC3403/AssignmentHistory', status=404 )

		return res

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_posting_and_bulk_downloading_file(self):
		from nti.assessment import response
		from nti.assessment import submission
		from cStringIO import StringIO
		from zipfile import ZipFile
		from nti.externalization import internalization
		from hamcrest import not_none
		q_sub = submission.QuestionSubmission( questionId="1", parts=(response.QUploadedFile(data=b'1234',
																							 contentType=b'text/plain',
																							 filename='foo.txt'),) )

		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id, questions=(q_sub,))
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))
		GIF_DATAURL = b'data:image/gif;base64,R0lGODlhCwALAIAAAAAA3pn/ZiH5BAEAAAEALAAAAAALAAsAAAIUhA+hkcuO4lmNVindo7qyrIXiGBYAOw=='

		ext_obj = to_external_object(submission)
		ext_obj['parts'][0]['questions'][0]['parts'][0]['value'] = GIF_DATAURL

		assert_that( internalization.find_factory_for( ext_obj ),
				 is_( not_none() ) )
		# Make sure we're enrolled
		res = self.testapp.post_json( '/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses',
									  'CLC 3403',
									  status=201 )
		enrollment_history_link = self.require_link_href_with_rel( res.json_body, 'AssignmentHistory')
		course_history_link = self.require_link_href_with_rel( res.json_body['CourseInstance'], 'AssignmentHistory')

		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id,
									  ext_obj)
		self._check_submission(res, enrollment_history_link)

		# Our default user happens to have admin permisions

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id + '/BulkFilePartDownload')

		assert_that( res.content_disposition, is_( 'attachment; filename="assignment.zip"'))

		data = res.body
		io = StringIO(data)
		zipfile = ZipFile(io, 'r')

		assert_that( zipfile.namelist(), contains( 'sjohnson@nextthought.com/0/0/0/foo.txt'))
