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

from zope.cachedescriptors.property import Lazy

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItem
from .feedback import UsersCourseAssignmentHistoryItemFeedbackContainer

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
		if submission.__parent__ is not None or pending.__parent__ is not None:
			raise ValueError("Objects already parented")

		item = UsersCourseAssignmentHistoryItem(Submission=submission,
												pendingAssessment=pending )
		submission.__parent__ = item
		pending.__parent__ = item

		lifecycleevent.created(item)
		self[submission.assignmentId] = item # fire object added

		# Fire object added for the submission and assessment, now that they have
		# homes in the containment tree
		lifecycleevent.added(submission)
		lifecycleevent.added(pending)

		return item


@interface.implementer(IUsersCourseAssignmentHistoryItem)
class UsersCourseAssignmentHistoryItem(PersistentCreatedModDateTrackingObject,
									   Contained,
									   SchemaConfigured):
	createDirectFieldProperties(IUsersCourseAssignmentHistoryItem)

	__external_can_create__ = False

	@Lazy
	def Feedback(self):
		container = UsersCourseAssignmentHistoryItemFeedbackContainer()
		container.__parent__ = self
		container.__name__ = 'Feedback'
		self._p_changed = True
		return container
