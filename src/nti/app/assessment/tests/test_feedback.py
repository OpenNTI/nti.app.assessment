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
from hamcrest import contains
from hamcrest import same_instance
from hamcrest import is_

from .. import feedback
from .. import interfaces

from nti.testing.matchers import validly_provides

import unittest

class TestFeedback(unittest.TestCase):
	def test_interfaces(self):
		item = feedback.UsersCourseAssignmentHistoryItemFeedback()
		item.creator = 'foo' # anything is accepted eventually
		assert_that( item,
					 validly_provides( interfaces.IUsersCourseAssignmentHistoryItemFeedback ))

		assert_that( feedback.UsersCourseAssignmentHistoryItemFeedbackContainer(),
					 validly_provides( interfaces.IUsersCourseAssignmentHistoryItemFeedbackContainer ) )


	def test_inserting_deleting(self):
		container = feedback.UsersCourseAssignmentHistoryItemFeedbackContainer()
		for _ in range(25):
			container['ignored'] = feedback.UsersCourseAssignmentHistoryItemFeedback()

		assert_that( container.keys(),
					 contains( *[str(i) for i in range(25)]  ) )

		# Once we had a problem where if we deleted an item and then added
		# another item, we would get a key conflict
		del container['0']
		del container['15']

		item = feedback.UsersCourseAssignmentHistoryItemFeedback()
		container['ignored'] = item
		# last key,
		assert_that( container['25'], is_( same_instance(item)) )
		# and still last value
		assert_that( container.Items[-1], is_( same_instance(item)) )

		# Same for in the middle
		item = feedback.UsersCourseAssignmentHistoryItemFeedback()
		container['ignored'] = item
		# last key,
		assert_that( container['26'], is_( same_instance(item)) )
		# but still last value
		assert_that( container.Items[-1], is_( same_instance(item)) )
