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
from hamcrest import is_not
from hamcrest import none
from hamcrest import has_key
from hamcrest import has_entries
from hamcrest import has_length
from hamcrest import has_properties
from hamcrest import contains
from hamcrest import calling
from hamcrest import raises

from nti.dataserver.tests import mock_dataserver
from nti.testing.matchers import validly_provides

import os
from zope import component
import datetime

from nti.app.testing.application_webtest import SharedApplicationTestBase
from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.filesystem import CachedNotifyingStaticFilesystemLibrary as Library

from nti.app.products.courseware.tests import test_catalog_from_content

from nti.assessment.assignment import QAssignmentPart, QAssignment
from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission
from nti.assessment import interfaces as asm_interfaces
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from ..adapters import _begin_assessment_for_assignment_submission

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

		question_set_id = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"

		lib = component.getUtility(IContentPackageLibrary)

		clc = lib.contentPackages[0]

		question_set = component.getUtility(asm_interfaces.IQuestionSet,
											name=question_set_id)

		assignment_part = QAssignmentPart(question_set=question_set)
		assignment = QAssignment( parts=(assignment_part,) )
		assignment.__parent__ = clc
		assignment.__name__ = 'a'

		component.provideUtility( assignment,
								  provides=asm_interfaces.IQAssignment,
								  name="a" )

		cls.question_set = question_set
		cls.assignment = assignment
		cls.question_set_id = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"

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
		submission = AssignmentSubmission(assignmentId='a')

		assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
					 raises(ValueError, 'parts') )

	@WithSharedApplicationMockDS
	def test_before_open(self):
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId='a', parts=(qs_submission,))

		# Open tomorrow
		self.assignment.available_for_submission_beginning = (datetime.datetime.now() + datetime.timedelta(days=1))
		try:
			assert_that( calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
						 raises(ValueError, 'early') )
		finally:
			self.assignment.available_for_submission_beginning = None


	@WithSharedApplicationMockDS
	def test_pending(self):
		qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
		submission = AssignmentSubmission(assignmentId='a', parts=(qs_submission,))

		with mock_dataserver.mock_db_trans(self.ds):
			pending = IQAssignmentSubmissionPendingAssessment(submission)
		assert_that( pending, validly_provides(IQAssignmentSubmissionPendingAssessment))
		assert_that( pending.parts, contains(qs_submission))
