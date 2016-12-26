#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementations of the feedback content types.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.annotation.interfaces import IAttributeAnnotatable

from zope.container.constraints import checkObject

from zope.container.ordered import OrderedContainer

from zope.container.interfaces import IContainerModifiedEvent

from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from zope.mimetype.interfaces import IContentTypeAware

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.coremetadata.mixins import ContainedMixin

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.contenttypes.note import BodyFieldProperty

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.sharing import AbstractReadableSharedMixin

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.namedfile.constraints import FileConstraints
from nti.namedfile.interfaces import IFileConstraints

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import AdaptingFieldProperty

from nti.wref.interfaces import IWeakRef

@interface.implementer(IUsersCourseAssignmentHistoryItemFeedback,
					   IAttributeAnnotatable,
					   IContentTypeAware)
class UsersCourseAssignmentHistoryItemFeedback(PersistentCreatedModDateTrackingObject,
											   SchemaConfigured,
											   ContainedMixin,
											   AbstractReadableSharedMixin):

	__external_can_create = True

	parameters = {}  # IContentTypeAware
	mime_type = mimeType = "application/vnd.nextthought.assessment.userscourseassignmenthistoryitemfeedback"

	body = BodyFieldProperty(IUsersCourseAssignmentHistoryItemFeedback['body'])
	title = AdaptingFieldProperty(IUsersCourseAssignmentHistoryItemFeedback['title'])

	@property
	def creator(self):
		# as a Created object, we need to have a creator;
		# our default ACL provider uses that
		if self.__dict__.get('creator') is not None:
			creator = self.__dict__['creator']
			return creator() if callable(creator) else creator

		# If the user is deleted we won't be able to do this
		if self.__parent__ is not None:
			return IUser(self.__parent__.__parent__, None)
		return None

	@creator.setter
	def creator(self, nv):
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

	@property
	def sharingTargets(self):
		"""
		By design, the user cannot toggle feedback sharable properties.
		However, we define sharing targets here to expose change
		broadcasting.
		"""
		results = []
		creator = self.creator
		results.append(creator)
		course = ICourseInstance(self, None)
		if course is not None:
			instructors = (IUser(i, None) for i in course.instructors)
			results.extend((x for x in instructors if x))

		if self.__parent__ is not None:
			container_owner = IUser(self.__parent__.__parent__, None)
			if container_owner is not None:
				results.append(container_owner)
		return results

	@property
	def __acl__(self):
		aces = []
		# give all permissions to the owner
		creator = self.creator
		if creator is not None:
			aces.append(ace_allowing(creator, ALL_PERMISSIONS, type(self)))

		# read access for the instructors
		course = ICourseInstance(self, None)
		if course is not None:
			aces.extend(ace_allowing(i, ACT_READ, type(self))
				 		for i in course.instructors or ())

		# read access to the container feedback owner
		if self.__parent__ is not None:
			container_owner = IUser(self.__parent__.__parent__, None)
			if container_owner is not None and container_owner != creator:
				aces.append(ace_allowing(container_owner, ACT_READ, type(self)))
		aces.append(ACE_DENY_ALL)
		return acl_from_aces(aces)

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

	#: We want to inherit the read access for the instructors
	__acl_deny_all__ = False

	def __setitem__(self, key, value):
		# Choose first available key, starting from the end
		# (optimizing for the case that we're appending).
		# In this way our keys match our sort natural sort order
		count = len(self)
		key = '%d' % count
		while key in self:
			# this means something has previously been
			# deleted, so we've got a key gap. By sticking
			# to ordering the keys, this will be apparent.
			count += 1
			key = '%d' % count

		checkObject(self, key, value)
		super(UsersCourseAssignmentHistoryItemFeedbackContainer, self).__setitem__(key, value)
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

@component.adapter(IUsersCourseAssignmentHistoryItemFeedbackContainer,
				   IContainerModifiedEvent)
def when_feedback_container_modified_modify_history_item(container,
														 event,
														 update_mod=True):
	"""
	Because we directly surface the 'Feedback' container as an inline
	property of the history item, and not as a secondary link, it's important
	to clients that when the feedback item or its descendents are modified
	that the top-level history item is modified as well (so that they can
	depend on LastModified).
	"""
	try:
		if update_mod:
			# because we dont know what order these fire in,
			# the main last mod subscriber may or may not have run yet
			container.updateLastMod()
		container.__parent__.updateLastModIfGreater(container.lastModified)
	except AttributeError:
		pass

# likewise for simple modification events inside the container
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback,
				   IObjectModifiedEvent)
def when_feedback_modified_modify_history_item(feedback, event):
	try:
		feedback.updateLastMod()  # not sure of order
		container = feedback.__parent__
		container.updateLastModIfGreater(feedback.lastModified)
		when_feedback_container_modified_modify_history_item(container, event, False)
	except AttributeError:
		pass

@interface.implementer(IFileConstraints)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _AssignmentHistoryItemFeedbackFileConstraints(FileConstraints):
	max_file_size = 52428800 # 50 MB
