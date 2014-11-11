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
from zope import lifecycleevent
from zope.location.location import locate
from zope.container.contained import Contained
from zope.location.interfaces import LocationError
from zope.annotation.interfaces import IAnnotations
from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from ZODB.interfaces import IConnection

from pyramid.interfaces import IRequest

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.users import User
from nti.dataserver.interfaces import IACLProvider

from nti.dataserver.traversal import find_interface
from nti.dataserver.traversal import ContainerAdapterTraversable

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.externalization.interfaces import StandardExternalFields

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.utils.property import alias

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
	
	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.owner
		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		aces = [ace_allowing(self.owner, ALL_PERMISSIONS, UsersCourseAssignmentMetadata)]
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

@interface.implementer(IUsersCourseAssignmentMetadataItem,
					   IACLProvider)
class UsersCourseAssignmentMetadataItem(PersistentCreatedModDateTrackingObject,
										Contained,
										SchemaConfigured):
	createDirectFieldProperties(IUsersCourseAssignmentMetadataItem)

	__external_can_create__ = False

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
		aces = [ace_allowing(self.owner, ALL_PERMISSIONS, 
							 UsersCourseAssignmentMetadataItem)]
		aces.append(ACE_DENY_ALL)
		result = acl_from_aces( aces )
		return result

@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseAssignmentMetadataContainer)
def _metadatacontainer_for_course(course):
	annotations = IAnnotations(course)
	try:
		KEY = 'AssignmentMetadataContainer'
		result = annotations[KEY]
	except KeyError:
		result = UsersCourseAssignmentMetadataContainer()
		annotations[KEY] = result
		result.__name__ = KEY
		result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseAssignmentMetadataContainer)
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

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentMetadata)
def _course_from_metadata_lineage(item):
	course = find_interface(item, ICourseInstance, strict=False)
	if course is None:
		raise component.ComponentLookupError("Unable to find course")
	return course

@component.adapter(IUsersCourseAssignmentMetadataContainer, IRequest)
class _UsersCourseAssignmentMetaMapTraversable(ContainerAdapterTraversable):

	def traverse( self, key, remaining_path ):
		try:
			return super(_UsersCourseAssignmentMetaMapTraversable, self).traverse(key, remaining_path)
		except LocationError:
			user = User.get_user(key)
			if user is not None:
				return _metadata_for_user_in_course(self.context.__parent__, user)			
			raise		

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_metadatacontainer_for_course(course)
	
from .interfaces import IUsersCourseAssignmentHistoryItem

@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectRemovedEvent)
def _on_assignment_history_item_deleted(item, event):
	user = IUser(item, None)
	course = find_interface(item, ICourseInstance, strict=False)
	if user is not None and course is not None:
		pass
#		 assignment_metadata = component.getMultiAdapter((course, user),
#														 IUsersCourseAssignmentMetadata)
#		 TODO: Reemove
#		 assignment_metadata.removeSubmission(item.Submission)
	