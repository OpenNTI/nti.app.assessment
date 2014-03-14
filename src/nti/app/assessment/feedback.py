#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementations of the feedback content types.

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import interface

from zope.annotation.interfaces import IAttributeAnnotatable

from .interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer
from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.dataserver.datastructures import ContainedMixin
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject

from nti.utils.schema import AdaptingFieldProperty
from nti.utils.schema import SchemaConfigured
from nti.dataserver.contenttypes.note import BodyFieldProperty

from zope.container.ordered import OrderedContainer
from zope.container.constraints import checkObject

from nti.dataserver.interfaces import IUser
from nti.wref.interfaces import IWeakRef

@interface.implementer(IUsersCourseAssignmentHistoryItemFeedback,
					   IAttributeAnnotatable)
class UsersCourseAssignmentHistoryItemFeedback(PersistentCreatedModDateTrackingObject,
											   SchemaConfigured,
											   ContainedMixin):

	mimeType = None
	__external_can_create = True

	body = BodyFieldProperty(IUsersCourseAssignmentHistoryItemFeedback['body'])
	title = AdaptingFieldProperty(IUsersCourseAssignmentHistoryItemFeedback['title'])

	#: We want to inherit the read access for the instructors
	__acl_deny_all__ = False

	@property
	def creator(self):
		# as a Created object, we need to have a creator;
		# our default ACL provider uses that
		if self.__dict__.get('creator') is not None:
			creator = self.__dict__['creator']
			return creator() if callable(creator) else creator

		# If the user is deleted we won't be able to do this
		return IUser(self.__parent__.__parent__, None)

	@creator.setter
	def creator(self,nv):
		if nv is None:
			if 'creator' in self.__dict__:
				del self.__dict__['creator']
				self._p_changed = True
			return
		try:
			self.__dict__['creator'] = IWeakRef(nv)
		except TypeError:
			self.__dict__['creator'] = nv
		self._p_changed = True

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

	def __setitem__(self, key, value):
		key = "%s.%s" % (time.time(), len(self))
		checkObject(self, key, value )
		super(UsersCourseAssignmentHistoryItemFeedbackContainer,self).__setitem__( key, value )
		self.updateLastMod()

	@property
	def Items(self):
		return list(self.values())

	@property
	def creator(self):
		# as a Created object, we need to have a creator;
		# our default ACL provider uses that.
		# If the user is deleted, we won't be able to do this
		return IUser(self.__parent__, None)
