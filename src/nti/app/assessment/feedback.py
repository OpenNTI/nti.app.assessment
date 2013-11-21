#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementations of the feedback content types.

$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)


from zope import interface

from zope.annotation.interfaces import IAttributeAnnotatable

from .interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer
from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.dataserver.datastructures import ContainedMixin
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject

from nti.utils.schema import AdaptingFieldProperty
from nti.dataserver.contenttypes.note import BodyFieldProperty

from zope.container.ordered import OrderedContainer
from zope.container.constraints import checkObject


@interface.implementer(IUsersCourseAssignmentHistoryItemFeedback,
					   IAttributeAnnotatable)
class UsersCourseAssignmentHistoryItemFeedback(PersistentCreatedModDateTrackingObject,
											   ContainedMixin):

	mimeType = None
	__external_can_create = True

	body = BodyFieldProperty(IUsersCourseAssignmentHistoryItemFeedback['body'])
	title = AdaptingFieldProperty(IUsersCourseAssignmentHistoryItemFeedback['title'])


@interface.implementer(IUsersCourseAssignmentHistoryItemFeedbackContainer,
					   IAttributeAnnotatable)
class UsersCourseAssignmentHistoryItemFeedbackContainer(PersistentCreatedModDateTrackingObject,
														OrderedContainer):
	"""
	Container for feedback items. We extend OrderedContainer
	mostly because it's a much lighter weight object than a btree
	container, and we don't expect to need many items.

	As an implementation of :class:`.IContainerNamesContainer`, we
	choose our own keys; what you pass to the set method is ignored.
	"""

	def __setitem__( self, key, value ):
		key = str(len(self))
		checkObject(self, key, value )

		super.__setitem__( key, value )
		self.updateLastModified()
