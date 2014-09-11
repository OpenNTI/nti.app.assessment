#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import assert_that
from hamcrest import has_property

import weakref

from nti.app.assessment.history import UsersCourseAssignmentHistory
from nti.app.assessment.history import UsersCourseAssignmentHistories
from nti.app.assessment.history import UsersCourseAssignmentHistoryItem

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemSummary

from nti.assessment.submission import AssignmentSubmission
from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser

from nti.testing.matchers import validly_provides
from nti.testing.matchers import is_false

from nti.app.assessment.tests import AssessmentLayerTest

class TestHistory(AssessmentLayerTest):
	# NOTE: We don't actually need all this setup the layer does,
	# but it saves time when we run in bulk

	def test_provides(self):
		histories = UsersCourseAssignmentHistories()
		history = UsersCourseAssignmentHistory()
		history.__parent__ = histories
		# Set an owner; use a python wref instead of the default
		# adapter to wref as it requires an intid utility
		history.owner = weakref.ref(User('sjohnson@nextthought.com'))
		item = UsersCourseAssignmentHistoryItem()
		item.creator = 'foo'
		item.__parent__ = history
		assert_that( item,
					 validly_provides(IUsersCourseAssignmentHistoryItem))

		assert_that( history,
					 validly_provides(IUsersCourseAssignmentHistory))
		assert_that( IUser(item), is_(history.owner))
		assert_that( IUser(history), is_(history.owner))

		summ = IUsersCourseAssignmentHistoryItemSummary(item)
		assert_that( summ,
					 validly_provides(IUsersCourseAssignmentHistoryItemSummary))

	def test_record(self):
		history = UsersCourseAssignmentHistory()
		submission = AssignmentSubmission(assignmentId='b')
		pending =  QAssignmentSubmissionPendingAssessment( assignmentId='b',
														   parts=() )

		item = history.recordSubmission( submission, pending )
		assert_that( item, has_property( 'Submission', is_( submission )))
		assert_that( item, has_property( '__name__', is_( submission.assignmentId)) )

		assert_that( item.__parent__, is_( history ))

		assert_that( history, has_property( 'lastViewed', 0 ))


	def test_nuclear_option(self):
		history = UsersCourseAssignmentHistory()
		submission = AssignmentSubmission(assignmentId='b')
		pending =  QAssignmentSubmissionPendingAssessment( assignmentId='b',
														   parts=() )

		item = history.recordSubmission( submission, pending )

		# in the absence of info, it's false
		assert_that(item, has_property('_student_nuclear_reset_capable', is_false()))
