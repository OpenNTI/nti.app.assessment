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
from hamcrest import has_key
from hamcrest import has_entry

from nti.testing import base
from nti.testing import matchers

from .. import feedback
from .. import interfaces

from nti.testing.matchers import validly_provides


def test_interfaces():
	assert_that( feedback.UsersCourseAssignmentHistoryItemFeedback(),
				 validly_provides( interfaces.IUsersCourseAssignmentHistoryItemFeedback ))

	assert_that( feedback.UsersCourseAssignmentHistoryItemFeedbackContainer(),
				 validly_provides( interfaces.IUsersCourseAssignmentHistoryItemFeedbackContainer ) )
