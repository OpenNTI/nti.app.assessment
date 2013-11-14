#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Storage for assignment histories.

.. note:: Even though these are adapters and so might have gone in the
  :mod:`adapters` module, they are also persistent, and as such deserve their
  own module.

$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import lifecycleevent

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItem

from zope.container.contained import Contained

from nti.utils.schema import SchemaConfigured
from nti.utils.schema import createDirectFieldProperties

from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject
from nti.dataserver.containers import CheckingLastModifiedBTreeContainer

@interface.implementer(IUsersCourseAssignmentHistory)
class UsersCourseAssignmentHistory(CheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course assignment history for a user (within a course
	although theoretically, because assignment IDs are globally unique,
	we could use a single history).

	Although the primary interface this class implements does not specify the full
	container interface, we do provide it as a side effect.
	"""


	def recordSubmission( self, submission, pending ):
		item = UsersCourseAssignmentHistoryItem(Submission=submission,
												pendingAssessment=pending )
		lifecycleevent.created(item)
		self[submission.assignmentId] = item
		return item


@interface.implementer(IUsersCourseAssignmentHistoryItem)
class UsersCourseAssignmentHistoryItem(PersistentCreatedModDateTrackingObject,
									   Contained,
									   SchemaConfigured):
	createDirectFieldProperties(IUsersCourseAssignmentHistoryItem)
