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
