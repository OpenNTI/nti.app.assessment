#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from nti.testing.layers import find_test
from nti.testing.layers import GCLayerMixin
from nti.testing.layers import ZopeComponentLayer
from nti.testing.layers import ConfiguringLayerMixin

from nti.dataserver.tests.mock_dataserver import DSInjectorMixin

import zope.testing.cleanup

class SharedConfiguringTestLayer(ZopeComponentLayer,
								 GCLayerMixin,
								 ConfiguringLayerMixin,
								 DSInjectorMixin):
	set_up_packages = ('nti.appserver', 'nti.app.assessment')

	@classmethod
	def setUp(cls):
		cls.setUpPackages()

	@classmethod
	def tearDown(cls):
		cls.tearDownPackages()
		zope.testing.cleanup.cleanUp()

	@classmethod
	def testSetUp(cls, test=None):
		test = test or find_test()
		cls.setUpTestDS(test)

	@classmethod
	def testTearDown(cls):
		pass

import unittest

class AssessmentLayerTest(unittest.TestCase):
	layer = SharedConfiguringTestLayer

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer
from nti.app.products.courseware.tests import publish_ou_course_entries
from nti.app.testing.application_webtest import ApplicationTestLayer

from nti.contentlibrary.interfaces import IContentPackageLibrary

from zope import component

from nti.assessment.assignment import QAssignmentPart, QAssignment
from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission
from nti.assessment import interfaces as asm_interfaces
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment
from nti.assessment.interfaces import IQAssessmentItemContainer

import ZODB
from nti.dataserver.tests.mock_dataserver import WithMockDS
from nti.dataserver.tests.mock_dataserver import mock_db_trans

import datetime

class RegisterAssignmentLayer(InstructedCourseApplicationTestLayer):

	@classmethod
	def _register_assignment(cls):

		def install_questions():
			lib = component.getUtility(IContentPackageLibrary)
			
			poll_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.pollid.aristotle.1"
			survey_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.survey:KNOWING_aristotle"
			
			assignment_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle"
			question_set_id  = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
			
			question_set = component.getUtility(asm_interfaces.IQuestionSet,
												name=question_set_id)

			## add a assignment with a future date
			due_date = datetime.datetime.today()
			due_date = due_date.replace(year=due_date.year + 1)
			
			assignment_part = QAssignmentPart(question_set=question_set, 
											  auto_grade=True)
			
			assignment = QAssignment( parts=(assignment_part,), 
									  available_for_submission_ending=due_date )
			assignment.__name__ = assignment.ntiid = assignment_ntiid

			component.getSiteManager().registerUtility( assignment,
														provided=asm_interfaces.IQAssignment,
														name=assignment_ntiid )

			## Also make sure this assignment is found in the assignment index
			## at the same container that that has the quiz data
			lesson_page_id = "tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:QUIZ_01.01"
			lesson = lib.pathToNTIID(lesson_page_id)[-1]
			assignment.__parent__ = lesson
			asm_cont = IQAssessmentItemContainer(lesson)
			asm_cont.append(assignment)

			cls.poll_id = poll_ntiid
			cls.survey_id = survey_ntiid
			
			cls.question_set = question_set
			cls.question_set_id = question_set_id
			cls.question_id = 'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.qid.aristotle.1'
			
			cls.lesson_page_id = lesson_page_id
			cls.assignment_id = assignment_ntiid

		from nti.contenttypes.courses.interfaces import ICourseCatalog

		database = ZODB.DB(ApplicationTestLayer._storage_base, database_name='Users')

		@WithMockDS(database=database)
		def _sync():
			with mock_db_trans(site_name='platform.ou.edu'):
				install_questions()
				catalog = component.getUtility( ICourseCatalog )
				try:
					from nti.app.products.courseware.interfaces import ICourseInstance
					from nti.app.products.gradebook.assignments import synchronize_gradebook
					for c in catalog.iterCatalogEntries():
						synchronize_gradebook(ICourseInstance(c, None))
				except ImportError:
					pass
		_sync()

	@classmethod
	def setUp(cls):
		cls._register_assignment()

	@classmethod
	def tearDown(cls):
		# Must implement!
		pass

	@classmethod
	def setUpTest(cls):
		pass

	@classmethod
	def tearDownTest(cls):
		pass

class RegisterAssignmentsForEveryoneLayer(RegisterAssignmentLayer):


	@classmethod
	def setUp(cls):
		from ..assignment_filters import UserEnrolledForCreditInCourseOrInstructsFilter
		UserEnrolledForCreditInCourseOrInstructsFilter.TEST_OVERRIDE = True

	@classmethod
	def tearDown(cls):
		# Must implement!

		from ..assignment_filters import UserEnrolledForCreditInCourseOrInstructsFilter
		UserEnrolledForCreditInCourseOrInstructsFilter.TEST_OVERRIDE = False

	@classmethod
	def setUpTest(cls):
		pass

	@classmethod
	def tearDownTest(cls):
		pass

class RegisterAssignmentLayerMixin(object):
	
	poll_id = None
	survey_id = None
	
	question_id = None
	question_set = None
	question_set_id = None
	
	assignment_id = None
	lesson_page_id = None
	
	def setUp(self):
		super(RegisterAssignmentLayerMixin,self).setUp()
		self.question_id = RegisterAssignmentLayer.question_id
		self.question_set = RegisterAssignmentLayer.question_set
		self.question_set_id = RegisterAssignmentLayer.question_set_id
		
		self.lesson_page_id = RegisterAssignmentLayer.lesson_page_id
		self.assignment_ntiid = self.assignment_id = RegisterAssignmentLayer.assignment_id
