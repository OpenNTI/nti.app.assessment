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
from hamcrest import none
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
from hamcrest import is_not
does_not = is_not

from nti.dataserver.tests import mock_dataserver
from nti.testing.matchers import validly_provides
from nti.testing.matchers import is_empty

import os
from zope import component
from zope.schema.interfaces import ConstraintNotSatisfied
from zope.schema.interfaces import NotUnique
import datetime

from nti.app.testing.application_webtest import SharedApplicationTestBase
from nti.app.testing.application_webtest import ApplicationLayerTest
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

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

class _RegisterAssignmentLayer(InstructedCourseApplicationTestLayer):

	@classmethod
	def _register_assignment(cls):
		lib = component.getUtility(IContentPackageLibrary)

		clc = lib.contentPackages[0]
		question_set_id  = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
		assignment_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle"

		question_set = component.getUtility(asm_interfaces.IQuestionSet,
											name=question_set_id)

		assignment_part = QAssignmentPart(question_set=question_set, auto_grade=True)
		due_date = datetime.datetime.today()
		due_date = due_date.replace(year=due_date.year + 1)
		assignment = QAssignment( parts=(assignment_part,), available_for_submission_ending=due_date )
		assignment.__name__ = assignment.ntiid = assignment_ntiid

		component.provideUtility( assignment,
								  provides=asm_interfaces.IQAssignment,
								  name=assignment_ntiid )

		# Also make sure this assignment is found in the assignment index
		# at the same container that that has the quiz data
		lesson_page_id = "tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:QUIZ_01.01"
		lesson = lib.pathToNTIID(lesson_page_id)[-1]
		assignment.__parent__ = lesson
		IQAssessmentItemContainer(lesson).append(assignment)

		cls.question_set = question_set
		cls.assignment = assignment
		cls.question_set_id = question_set_id
		cls.assignment_id = assignment_ntiid
		cls.lesson_page_id = lesson_page_id
		cls.question_id = 'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.qid.aristotle.1'


		from zope.component.interfaces import IComponents
		from nti.app.products.courseware.interfaces import ICourseCatalog
		components = component.getUtility(IComponents, name='platform.ou.edu')
		catalog = components.getUtility( ICourseCatalog )
		# XXX
		# This test is unclean, we re-register globally
		global_catalog = component.getUtility(ICourseCatalog)
		global_catalog._entries[:] = catalog._entries

	@classmethod
	def setUp(cls):
		cls._register_assignment()

	@classmethod
	def tearDown(cls):
		# Must implement!
		pass

class _RegisterAssignmentsForEveryoneLayer(_RegisterAssignmentLayer):


	@classmethod
	def setUp(cls):
		from ..assignment_filters import UserEnrolledForCreditInCourseOrInstructsFilter
		UserEnrolledForCreditInCourseOrInstructsFilter.TEST_OVERRIDE = True

	@classmethod
	def tearDown(cls):
		# Must implement!

		from ..assignment_filters import UserEnrolledForCreditInCourseOrInstructsFilter
		UserEnrolledForCreditInCourseOrInstructsFilter.TEST_OVERRIDE = False

class _RegisterAssignmentLayerMixin(object):
	question_set = None
	assignment = None
	question_set_id = None
	assignment_id = None
	lesson_page_id = None
	question_id = None

	def setUp(self):
		super(_RegisterAssignmentLayerMixin,self).setUp()
		self.question_set = _RegisterAssignmentLayer.question_set
		self.question_set_id = _RegisterAssignmentLayer.question_set_id
		self.assignment = _RegisterAssignmentLayer.assignment
		self.assignment_id = _RegisterAssignmentLayer.assignment_id
		self.question_id = _RegisterAssignmentLayer.question_id
		self.lesson_page_id = _RegisterAssignmentLayer.lesson_page_id

class TestAssignmentGrading(_RegisterAssignmentLayerMixin,ApplicationLayerTest):
	layer = _RegisterAssignmentsForEveryoneLayer
	features = ('assignments_for_everyone',)

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
					 raises(ConstraintNotSatisfied, 'parts') )

	@WithSharedApplicationMockDS
	def test_before_open(self):
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		# Open tomorrow
		self.assignment.available_for_submission_beginning = (datetime.datetime.utcnow() + datetime.timedelta(days=1))
		try:
			assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
						 raises(ConstraintNotSatisfied, 'early') )
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
			#assert_that( pending.parts, contains(qs_submission))

		# If we try again, we fail
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))
		with mock_dataserver.mock_db_trans(self.ds):

			user = User.get_user( self.extra_environ_default_user )
			submission.creator = user
			assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
						 raises(NotUnique, 'already submitted') )

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

	def _check_submission(self, res, history=None, last_viewed=0):
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
			assert_that( res.json_body, has_entry('lastViewed', last_viewed))
		else:
			# Because we're not enrolled...actually, we shouldn't
			# have been able to submit...this is here to make sure something
			# breaks when acls change
			res = self._fetch_user_url( '/Courses/EnrolledCourses/CLC3403/AssignmentHistories/sjohnson@nextthought.com', status=404 )

		return res

	@WithSharedApplicationMockDS(users=True,testapp=True,default_authenticate=True)
	def test_pending_application_assignment(self):
		# This only works in the OU environment because that's where the purchasables are
		extra_env = self.testapp.extra_environ or {}
		extra_env.update( {b'HTTP_ORIGIN': b'http://janux.ou.edu'} )
		self.testapp.extra_environ = extra_env


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

		assert_that( enrollment_history_link,
					 is_('/dataserver2/users/sjohnson%40nextthought.com/Courses/EnrolledCourses/CLC3403/AssignmentHistories/sjohnson@nextthought.com'))

		assert_that( course_history_link,
					 is_('/dataserver2/users/CLC3403.ou.nextthought.com/LegacyCourses/CLC3403/AssignmentHistories/sjohnson@nextthought.com'))

		# Both history links are equivalent and work; and both are empty before I submit
		for link in course_history_link, enrollment_history_link:
			history_res = self.testapp.get(link)
			assert_that( history_res.json_body, has_entry('Items', has_length(0)))


		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id,
									  ext_obj)
		self._check_submission(res, enrollment_history_link)

		history_res = self._check_submission( res, course_history_link )
		last_viewed_href = self.require_link_href_with_rel( history_res.json_body, 'lastViewed' )
		__traceback_info__ = history_res.json_body
		history_feedback_container_href = history_res.json_body['Items'].items()[0][1]['Feedback']['href']

		# The user can send some feedback
		feedback = UsersCourseAssignmentHistoryItemFeedback(body=['Some feedback'])
		ext_feedback = to_external_object(feedback)
		__traceback_info__ = ext_feedback
		res = self.testapp.post_json( history_feedback_container_href,
									  ext_feedback,
									  status=201 )

		# He can edit it
		feedback_item_edit_link = self.require_link_href_with_rel( res.json_body, 'edit' )
		new_feedback = dict(res.json_body)
		new_feedback['body'] = ['Other feedback']

		res = self.testapp.put_json( feedback_item_edit_link, new_feedback )
		assert_that( res.json_body, has_entry( 'body', ['Other feedback']) )

		# Both history links are equivalent and work
		for link in course_history_link, enrollment_history_link:
			history_res = self.testapp.get(link)
			assert_that( history_res.json_body, has_entry('Items', has_length(1)))
			item = history_res.json_body['Items'].values()[0]
			feedback = item['Feedback']
			assert_that( feedback, has_entry('Items', has_length(1)))
			assert_that( feedback['Items'], has_item( has_entry( 'body', ['Other feedback'])))
			assert_that( feedback['Items'], has_item( has_entry( 'href',
																 ends_with('AssignmentHistories/sjohnson%40nextthought.com/tag%3Anextthought.com%2C2011-10%3AOU-NAQ-CLC3403_LawAndJustice.naq.asg%3AQUIZ1_aristotle/Feedback/0') ) ) )

		# We can modify the view date by putting to the field
		res = self.testapp.put_json(last_viewed_href, 1234)
		history_res = self.testapp.get(course_history_link)
		assert_that(history_res.json_body, has_entry('lastViewed', 1234))

		# Of course, trying to PUT directly to the object 404s (not 500, we've
		# seen clients attempt this in the wild)
		self.testapp.put_json( course_history_link + '?_dc=1234/lastViewed', 2345, status=404 )

		instructor_environ = self._make_extra_environ(username='harp4162')

		# The instructor sees our submission in his activity view, as well as the feedback
		activity_link = '/dataserver2/users/CLC3403.ou.nextthought.com/LegacyCourses/CLC3403/CourseActivity'
		res = self.testapp.get(activity_link, extra_environ=instructor_environ)
		assert_that( res.json_body, has_entry('TotalItemCount', 2) )
		assert_that( res.json_body['Items'], contains( has_entries('Class', 'UsersCourseAssignmentHistoryItemFeedback',
																   'AssignmentId', 'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle'),
													   has_entry('Class', 'AssignmentSubmission')))

		# We can delete our own feedback item and it vanishes completely
		# TODO: Wouldn't a deleted object placeholder be better?
		self.testapp.delete(feedback_item_edit_link)
		for link in course_history_link, enrollment_history_link:
			history_res = self.testapp.get(link)
			item = history_res.json_body['Items'].values()[0]
			feedback = item['Feedback']
			assert_that( feedback, has_entry('Items', has_length(0)))

		res = self.testapp.get(activity_link, extra_environ=instructor_environ)
		assert_that( res.json_body, has_entry('TotalItemCount', 1) )
		assert_that( res.json_body['Items'], contains(has_entry('Class', 'AssignmentSubmission')))


		# The instructor can delete our submission
		self.testapp.delete(item['href'], extra_environ=instructor_environ, status=204)
		# Which empties out the activity
		res = self.testapp.get(activity_link, extra_environ=instructor_environ)
		assert_that( res.json_body, has_entry('TotalItemCount', 0) )
		assert_that( res.json_body, has_entry( 'Items', is_empty() ))

		# Whereupon we can submit again
		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id,
									  ext_obj)
		self._check_submission(res, enrollment_history_link, 1234)


	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_assignment_items_view(self):
		# This only works in the OU environment because that's where the purchasables are
		extra_env = self.testapp.extra_environ or {}
		extra_env.update( {b'HTTP_ORIGIN': b'http://janux.ou.edu'} )
		self.testapp.extra_environ = extra_env

		# Make sure we're enrolled
		res = self.testapp.post_json( '/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses',
									  'CLC 3403',
									  status=201 )
		enrollment_history_link = self.require_link_href_with_rel( res.json_body, 'AssignmentHistory')

		enrollment_assignments = self.require_link_href_with_rel( res.json_body, 'AssignmentsByOutlineNode')
		self.require_link_href_with_rel( res.json_body['CourseInstance'], 'AssignmentsByOutlineNode')

		res = self.testapp.get(enrollment_assignments)
		assert_that( res.json_body, has_entry(self.lesson_page_id,
											  contains( has_entries( 'Class', 'Assignment',
																	 'NTIID', self.assignment.__name__ ))))

		# The due date strips these
		assg = res.json_body[self.lesson_page_id][0]
		for part in assg['parts']:
			question_set = part['question_set']
			for question in question_set['questions']:
				for qpart in question['parts']:
					assert_that( qpart, has_entries('solutions', None,
												   'explanation', None))

		# If we submit...
		from nti.assessment.submission import QuestionSubmission
		question_id = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.qid.aristotle.1"
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id,
											  questions=(QuestionSubmission(questionId=question_id, parts=[0]),))
		submission = AssignmentSubmission(assignmentId=self.assignment_id, parts=(qs_submission,))

		ext_obj = to_external_object( submission )
		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id,
									  ext_obj)

		def _check_pending(pending):
			for assessed_qset in pending['parts']:
				for question in assessed_qset['questions']:
					for qpart in question['parts']:
						assert_that( qpart, has_entries('solutions', None,
														'explanation', None))

		_check_pending(res.json_body)
		# ... and get history
		history_res = self._check_submission(res, enrollment_history_link)

		# ... the assessd parts are also stripped
		history_item = next(iter(history_res.json_body['Items'].values()))

		pending = history_item['pendingAssessment']
		_check_pending(pending)


class _RegisterFileAssignmentLayer(InstructedCourseApplicationTestLayer):

	@classmethod
	def setUp(cls):


		question_set_id  = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
		assignment_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle"
		cls.question_set_id = question_set_id
		cls.assignment_id = assignment_ntiid

		from nti.assessment import parts
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
		cls.lesson_page_id = lesson_page_id
		lesson = lib.pathToNTIID(lesson_page_id)[-1]
		assignment.__parent__ = lesson
		IQAssessmentItemContainer(lesson).append(assignment)

	@classmethod
	def tearDown(cls):
		# MUST implement
		pass


class TestAssignmentFileGrading(ApplicationLayerTest):
	layer = _RegisterFileAssignmentLayer

	assignment_id = None
	question_set_id = None
	lesson_page_id = None

	def setUp(self):
		super(TestAssignmentFileGrading,self).setUp()
		self.assignment_id = _RegisterFileAssignmentLayer.assignment_id
		self.lesson_page_id = _RegisterFileAssignmentLayer.lesson_page_id
		self.question_set_id = _RegisterFileAssignmentLayer.question_set_id


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
			res = self._fetch_user_url( '/Courses/EnrolledCourses/CLC3403/AssignmentHistories/sjohnsen@nextthought.com', status=404 )

		return res

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_posting_and_bulk_downloading_file(self):
		# This only works in the OU environment because that's where the purchasables are
		extra_env = self.testapp.extra_environ or {}
		extra_env.update( {b'HTTP_ORIGIN': b'http://janux.ou.edu'} )
		self.testapp.extra_environ = extra_env

		from nti.assessment import response
		from nti.assessment import submission
		from cStringIO import StringIO
		from zipfile import ZipFile
		from nti.externalization import internalization
		from hamcrest import not_none
		q_sub = submission.QuestionSubmission( questionId="1", parts=(response.QUploadedFile(data=b'1234',
																							 contentType=b'image/gif',
																							 filename='foo.gif'),) )

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
		self.require_link_href_with_rel( res.json_body['CourseInstance'], 'AssignmentHistory')

		res = self.testapp.post_json( '/dataserver2/Objects/' + self.assignment_id,
									  ext_obj)
		history_res = self._check_submission(res, enrollment_history_link)

		# Now we should be able to find and download our data
		submission = history_res.json_body['Items'].values()[0]['Submission']
		submitted_file_part = submission['parts'][0]['questions'][0]['parts'][0]
		assert_that( submitted_file_part, has_key('url'))
		assert_that( submitted_file_part, has_key('value'))
		assert_that( submitted_file_part['url'], is_(submitted_file_part['value']) )
		assert_that( submitted_file_part, has_key('download_url'))

		# Once directly, as is consistent with the way that avatars, etc work
		download_res = self.testapp.get( submitted_file_part['url'] )
		assert_that( download_res, has_property('content_type', 'image/gif'))
		assert_that( download_res, has_property('content_length', 61))
		assert_that( download_res, has_property('content_disposition', none() ))

		# Then for download, both directly and without the trailing /view
		for path in submitted_file_part['url'][0:-5], submitted_file_part['download_url']:
			download_res = self.testapp.get( path )
			assert_that( download_res, has_property('content_type', 'image/gif'))
			assert_that( download_res, has_property('content_length', 61))
			assert_that( download_res, has_property('content_disposition', not_none() ))


		# Our default user happens to have admin perms to fetch the files
		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id )
		bulk_href = self.require_link_href_with_rel(res.json_body, 'ExportFiles')

		res = self.testapp.get(bulk_href)

		assert_that( res.content_disposition, is_( 'attachment; filename="assignment.zip"'))

		data = res.body
		io = StringIO(data)
		zipfile = ZipFile(io, 'r')

		name = 'sjohnson@nextthought.com-0-0-0-foo.gif'
		assert_that( zipfile.namelist(), contains( name ) )
		info = zipfile.getinfo(name)
		# Rounding means the second data may not be accurate
		assert_that( info.date_time[:5], is_( download_res.last_modified.timetuple()[:5] ) )

from nti.dataserver.interfaces import IUser
class IMySpecificUser(IUser):
	"marker"
from zope import interface
from nti.dataserver.mimetype import  nti_mimetype_with_class

class TestAssignmentFiltering(_RegisterAssignmentLayerMixin,ApplicationLayerTest):
	layer = _RegisterAssignmentLayer

	# With the feature missing

	@WithSharedApplicationMockDS(users=True,testapp=True, user_hook=lambda u: interface.alsoProvides(u, IMySpecificUser))
	def test_assignment_items_view(self):
		# This only works in the OU environment because that's where the purchasables are
		extra_env = self.testapp.extra_environ or {}
		extra_env.update( {b'HTTP_ORIGIN': b'http://janux.ou.edu'} )
		self.testapp.extra_environ = extra_env

		# Make sure we're enrolled
		res = self.testapp.post_json( '/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses',
									  'CLC 3403',
									  status=201 )

		enrollment_assignments = self.require_link_href_with_rel( res.json_body, 'AssignmentsByOutlineNode')
		enrollment_non_assignments = self.require_link_href_with_rel( res.json_body, 'NonAssignmentAssessmentItemsByOutlineNode')
		self.require_link_href_with_rel( res.json_body['CourseInstance'], 'AssignmentsByOutlineNode')

		res = self.testapp.get(enrollment_assignments)
		assert_that( res.json_body, # No assignments, we're not enrolled for credit
					 is_({u'href': u'/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses/CLC3403/AssignmentsByOutlineNode'}) )

		# It's also not on the page info, and the question sets it contains
		# aren't either
		lesson_page_id = "tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:QUIZ_01.01"
		question_set_id  = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
		page_info_mt = nti_mimetype_with_class( 'pageinfo' )

		res = self.fetch_by_ntiid( lesson_page_id,
								   headers={b'Accept': str(page_info_mt) })
		items = res.json_body.get('AssessmentItems', ())
		assert_that( items,
					 does_not( contains( has_entry('Class', 'Assignment')) ) )
		assert_that( items,
					 does_not( contains( has_entry('NTIID', question_set_id ) ) ) )
		assert_that( items, is_( () ) )

		# Nor are they in the non-assignment-items
		res = self.testapp.get(enrollment_non_assignments)
		assert_that( res.json_body, # Nothing, we're not enrolled for credit
					 has_entries(u'href', u'/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses/CLC3403/NonAssignmentAssessmentItemsByOutlineNode',
								 'tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:QUIZ_01.01', []) )


		# Now if we register a more specific adapter, we can claim to be enrolled
		from nti.app.products.courseware.interfaces import ILegacyCourseInstanceEnrollment
		from nti.app.products.courseware.interfaces import ILegacyCommunityBasedCourseInstance

		@interface.implementer(ILegacyCourseInstanceEnrollment)
		@component.adapter(ILegacyCommunityBasedCourseInstance,IMySpecificUser)
		class EnrollmentStatus(object):
			def __init__(self, course, user):
				pass

			LegacyEnrollmentStatus = 'ForCredit'

		component.provideAdapter(EnrollmentStatus)

		res = self.testapp.get(enrollment_assignments)
		assert_that( res.json_body, has_entry(self.lesson_page_id,
											  contains( has_entries( 'Class', 'Assignment',
																	 'NTIID', self.assignment.__name__ ))))

		# the question sets are still not actually available because they are in the assignment
		res = self.testapp.get(enrollment_non_assignments)
		assert_that( res.json_body,
					 has_entries(u'href', u'/dataserver2/users/sjohnson@nextthought.com/Courses/EnrolledCourses/CLC3403/NonAssignmentAssessmentItemsByOutlineNode',
								 'tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:QUIZ_01.01', is_empty() ) )

		# When we get the page info, only the assignment comes back,
		# not the things it contains
		res = self.fetch_by_ntiid( lesson_page_id,
								   headers={b'Accept': str(page_info_mt) })
		items = res.json_body.get('AssessmentItems', ())
		assert_that( items,
					 contains( has_entry('Class', 'Assignment')) )
		assert_that( items,
					 does_not( contains( has_entry('NTIID', question_set_id ) ) ) )

class TestNoteCreation(_RegisterAssignmentLayerMixin,ApplicationLayerTest):
	"We can not create notes an any component of an assignment"
	layer = _RegisterAssignmentLayer

	def _do_post(self, container):
		data = {'Class': 'Note',
				'ContainerId': container,
				'MimeType': 'application/vnd.nextthought.note',
				'applicableRange': {'Class': 'ContentRangeDescription'},
				'body': ['The body']}

		self.post_user_data( data, status=422 )

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_cannot_post_to_page(self):
		self._do_post(self.lesson_page_id)

	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_cannot_post_to_assignment(self):
		self._do_post(self.assignment_id)


	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_cannot_post_to_question_set(self):
		self._do_post(self.question_set_id)


	@WithSharedApplicationMockDS(users=True,testapp=True)
	def test_cannot_post_to_question(self):
		self._do_post(self.question_id)
