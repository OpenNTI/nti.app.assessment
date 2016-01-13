#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.contentsearch.interfaces import ISearchHitPredicate

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver.interfaces import IUser

from nti.traversal.traversal import find_interface

@interface.implementer(ISearchHitPredicate)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _AssignmentFeedbackItemSearchHitPredicate(object):

	def __init__(self, *args):
		pass

	def allow(self, feedback, score, query=None):
		result = True  # by default allow
		course = find_interface(feedback, ICourseInstance, strict=False)
		item = find_interface(feedback, IUsersCourseAssignmentHistoryItem, strict=False)
		user = IUser(item, None)  # get the user enrolled
		if course is not None and user is not None:
			enrollments = ICourseEnrollments(course)
			result = enrollments.get_enrollment_for_principal(user) is not None
		return result
