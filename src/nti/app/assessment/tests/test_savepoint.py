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

from nti.app.assessment.savepoint import UsersCourseAssignmentSavePoint
from nti.app.assessment.savepoint import UsersCourseAssignmentSavePoints
from nti.app.assessment.savepoint import UsersCourseAssignmentSavePointItem

from nti.app.assessment.interfaces import IUsersCourseAssignmentSavePoint
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavePointItem

from nti.assessment.submission import AssignmentSubmission

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser

from nti.testing.matchers import validly_provides

from nti.app.assessment.tests import AssessmentLayerTest

class TestHistory(AssessmentLayerTest):
	# NOTE: We don't actually need all this setup the layer does,
	# but it saves time when we run in bulk

	def test_provides(self):
		savepoints = UsersCourseAssignmentSavePoints()
		savepoint = UsersCourseAssignmentSavePoint()
		savepoint.__parent__ = savepoints
		# Set an owner; use a python wref instead of the default
		# adapter to wref as it requires an intid utility
		savepoint.owner = weakref.ref(User('sjohnson@nextthought.com'))
		item = UsersCourseAssignmentSavePointItem()
		item.creator = 'foo'
		item.__parent__ = savepoint
		assert_that( item,
					 validly_provides(IUsersCourseAssignmentSavePointItem))

		assert_that( savepoint,
					 validly_provides(IUsersCourseAssignmentSavePoint))
		assert_that( IUser(item), is_(savepoint.owner))
		assert_that( IUser(savepoint), is_(savepoint.owner))

	def test_record(self):
		savepoint = UsersCourseAssignmentSavePoint()
		submission = AssignmentSubmission(assignmentId='b')

		item = savepoint.recordSubmission( submission )
		assert_that( item, has_property( 'Submission', is_( submission )))
		assert_that( item, has_property( '__name__', is_( submission.assignmentId)) )
		assert_that( item.__parent__, is_( savepoint ))
