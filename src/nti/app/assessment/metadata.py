#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from zope import component
from zope import interface

from zope.container.contained import Contained

from zope.location.location import locate
from zope.location.interfaces import LocationError

from zope.annotation.interfaces import IAnnotations

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from pyramid.interfaces import IRequest

from nti.common.property import alias

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ACT_CREATE
from nti.dataserver.authorization import ACT_UPDATE

from nti.dataserver.users import User
from nti.dataserver.interfaces import IACLProvider

from nti.dataserver.traversal import find_interface
from nti.dataserver.traversal import ContainerAdapterTraversable

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.externalization.datastructures import InterfaceObjectIO
from nti.externalization.interfaces import IInternalObjectUpdater
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_ntiid_oid

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.wref.interfaces import IWeakRef

from .interfaces import IUsersCourseAssignmentMetadata
from .interfaces import IUsersCourseAssignmentMetadataItem
from .interfaces import IUsersCourseAssignmentMetadataContainer

LINKS = StandardExternalFields.LINKS

@interface.implementer(IUsersCourseAssignmentMetadataContainer)
class UsersCourseAssignmentMetadataContainer(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course assignment metadata for all users in a course.
	"""

@interface.implementer(IUsersCourseAssignmentMetadata)
class UsersCourseAssignmentMetadata(CheckingLastModifiedBTreeContainer):
	
	__external_can_create__ = False

	_owner_ref = None

	def _get_owner(self):
		return self._owner_ref() if self._owner_ref else None
	def _set_owner(self,owner):
		self._owner_ref = IWeakRef(owner)
	owner = property(_get_owner,_set_owner)

	#: A non-interface attribute for convenience (acls)
	creator = alias('owner')

	@property
	def Items(self):
		return dict(self)
	
	def get_or_create(self, assignmentId, start_time=None):
		if assignmentId not in self:
			start_time = float(start_time) if start_time is not None else start_time
			result = UsersCourseAssignmentMetadataItem(StartTime=start_time)
			self.append(assignmentId, result)
		else:
			result = self[assignmentId]
		return result
	getOrCreate = get_or_create
	
	def append(self, assignmentId, item):
		if item.__parent__ is not None:
			raise ValueError("Objects already parented")
		self[assignmentId] = item
		return item

	def remove(self, assignmentId, event=False):
		if assignmentId not in self:
			return

		item = self[assignmentId]
		if event:
			del self[assignmentId]
		else:
			self._delitemf(assignmentId, event=False)
			locate(item, None, None)
			self.updateLastMod()

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.owner
		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		creator = self.creator
		aces = [ace_allowing(creator, ACT_READ, UsersCourseAssignmentMetadata),
				ace_allowing(creator, ACT_CREATE, UsersCourseAssignmentMetadata)]
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

@interface.implementer(IUsersCourseAssignmentMetadataItem,
					   IACLProvider)
class UsersCourseAssignmentMetadataItem(PersistentCreatedModDateTrackingObject,
										Contained,
										SchemaConfigured):
	
	createDirectFieldProperties(IUsersCourseAssignmentMetadataItem)

	__external_can_create__ = True

	@property
	def id(self):
		return to_external_ntiid_oid(self)

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			try:
				return iface(self.__parent__)
			except (AttributeError,TypeError):
				return None

	@property
	def creator(self):
		return IUser(self, None)

	@creator.setter
	def creator(self, nv):
		pass

	@property
	def assignmentId(self):
		return self.__name__
	
	@property
	def __acl__(self):
		creator = self.creator
		aces = [ace_allowing(creator, ACT_READ, UsersCourseAssignmentMetadataItem),
				ace_allowing(creator, ACT_CREATE, UsersCourseAssignmentMetadataItem),
				ace_allowing(creator, ACT_UPDATE, UsersCourseAssignmentMetadataItem)]
		
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		for instructor in instructors:
			aces.append(ace_allowing(instructor, ALL_PERMISSIONS,
									 UsersCourseAssignmentMetadataItem))
		
		aces.append(ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS,
								 UsersCourseAssignmentMetadataItem)) 
		
		aces.append(ACE_DENY_ALL)			
		result = acl_from_aces( aces )
		return result

@interface.implementer(IInternalObjectUpdater)
@component.adapter(IUsersCourseAssignmentMetadataItem)
class _UsersCourseAssignmentMetadataItemUpdater(object):

	__slots__ = ('item',)

	def __init__(self, item):
		self.item = item

	def updateFromExternalObject(self, parsed, *args, **kwargs):
		start_time = parsed.get('StartTime', None)
		if self.item.StartTime is None:
			if isinstance(start_time, six.string_types):
				parsed['StartTime'] = float(start_time)
		else:
			parsed.pop('StartTime', None)
		result = InterfaceObjectIO(
					self.item,
					IUsersCourseAssignmentMetadataItem).updateFromExternalObject(parsed)
		return result
	
@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseAssignmentMetadataContainer)
def _metadatacontainer_for_course(course):
	annotations = IAnnotations(course)
	try:
		KEY = 'AssignmentMetadata'
		result = annotations[KEY]
	except KeyError:
		result = UsersCourseAssignmentMetadataContainer()
		annotations[KEY] = result
		result.__name__ = KEY
		result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseAssignmentMetadata)
def _metadata_for_user_in_course(course, user, create=True):
	result = None
	container = _metadatacontainer_for_course(course)
	try:
		result = container[user.username]
	except KeyError:
		if create:
			result = UsersCourseAssignmentMetadata()
			result.owner = user
			container[user.username] = result
	return result

def _metadatacontainer_for_course_path_adapter(course, request):
	return _metadatacontainer_for_course(course)

def _metadatacontainer_for_courseenrollment_path_adapter(enrollment, request):
	return _metadatacontainer_for_course( ICourseInstance(enrollment) )

from .adapters import _course_from_context_lineage

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentMetadataItem)
def _course_from_metadataitem_lineage(item):
	return _course_from_context_lineage(item, validate=True)

@component.adapter(IUsersCourseAssignmentMetadataContainer, IRequest)
class _UsersCourseAssignmentMetadataTraversable(ContainerAdapterTraversable):

	def traverse( self, key, remaining_path ):
		try:
			return super(_UsersCourseAssignmentMetadataTraversable, self).traverse(key, remaining_path)
		except LocationError:
			user = User.get_user(key)
			if user is not None:
				return _metadata_for_user_in_course(self.context.__parent__, user)			
			raise		

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_metadatacontainer_for_course(course)
	
import time

from .interfaces import IUsersCourseAssignmentHistoryItem

@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectAddedEvent)
def _on_assignment_history_item_added(item, event):
	user = IUser(item, None)
	course = find_interface(item, ICourseInstance, strict=False)
	assignment_metadata = component.queryMultiAdapter( (course, user),
														IUsersCourseAssignmentMetadata)
	if assignment_metadata is not None:
		meta_item = assignment_metadata.get_or_create(item.assignmentId, time.time())
		meta_item.Duration = time.time() - meta_item.StartTime
		meta_item.updateLastMod()

@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectRemovedEvent)
def _on_assignment_history_item_deleted(item, event):
	user = IUser(item, None)
	course = find_interface(item, ICourseInstance, strict=False)
	assignment_metadata = component.queryMultiAdapter( (course, user),
														IUsersCourseAssignmentMetadata)
	if assignment_metadata is not None:
		assignment_metadata.remove(item.assignmentId)
