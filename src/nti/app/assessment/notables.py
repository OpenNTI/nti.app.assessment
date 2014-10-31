#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Functions and architecture for general activity streams.

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.dataserver.interfaces import INotableFilter

@interface.implementer( INotableFilter )
class AssignmentFeedbackNotableFilter(object):
	"""
	Determines if assignment feedback is notable for the given user.
	Feedback is notable if it is on our user's assignments and the feedback
	is not created by our user.
	"""
	def __init__(self, context):
		self.context = context

	def is_notable(self, obj, user):
		result = False
		if IUsersCourseAssignmentHistoryItemFeedback.providedBy( obj ):
			history_item = obj.__parent__
			submission = history_item.Submission

			if 		submission.creator == user \
				and obj.creator != user:
				result = True
		return result
