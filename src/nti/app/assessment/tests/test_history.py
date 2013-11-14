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
from hamcrest import has_property
from hamcrest import has_entry

from nti.testing import base
from nti.testing.matchers import validly_provides

setUpModule = lambda: base.module_setup(set_up_packages=(__name__,))
tearDownModule = base.module_teardown

from ..history import UsersCourseAssignmentHistory
from ..history import UsersCourseAssignmentHistoryItem

from ..interfaces import IUsersCourseAssignmentHistoryItem
from ..interfaces import IUsersCourseAssignmentHistory

from nti.assessment.submission import AssignmentSubmission

def test_provides():
	history = UsersCourseAssignmentHistory()
	item = UsersCourseAssignmentHistoryItem()
	item.creator = 'foo'
	item.__parent__ = history
	assert_that( item,
				 validly_provides(IUsersCourseAssignmentHistoryItem))

	assert_that( history,
				 validly_provides(IUsersCourseAssignmentHistory))

def test_record():
	history = UsersCourseAssignmentHistory()
	submission = AssignmentSubmission(assignmentId='b')

	item = history.recordSubmission( submission, None )
	assert_that( item, has_property( 'Submission', is_( submission )))
	assert_that( item, has_property( '__name__', is_( submission.assignmentId)) )

	assert_that( item.__parent__, is_( history ))
