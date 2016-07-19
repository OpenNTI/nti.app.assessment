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

from zope.annotation.interfaces import IAnnotations

from zope.container.contained import Contained

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from zope.location.interfaces import LocationError
from zope.location.interfaces import ISublocations

from zope.location.location import locate

from ZODB.interfaces import IConnection

from pyramid.interfaces import IRequest

from nti.app.assessment._submission import set_submission_lineage
from nti.app.assessment._submission import transfer_submission_file_data

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepointItem

from nti.assessment.interfaces import IQAssessment

from nti.common.property import alias

from nti.containers.containers import CheckingLastModifiedBTreeContainer
from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.authorization import ACT_READ

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IACLProvider

from nti.dataserver.users import User

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.externalization.interfaces import StandardExternalFields

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable

from nti.wref.interfaces import IWeakRef

LINKS = StandardExternalFields.LINKS

@interface.implementer(IUsersCourseAssignmentSavepoints)
class UsersCourseAssignmentSavepoints(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course assignment save points for all users in a course.
	"""

	def has_assignment(self, assignment_id):
		for savepoint in list(self.values()):
			if assignment_id in savepoint:
				return True
		return False

@interface.implementer(IUsersCourseAssignmentSavepoint)
class UsersCourseAssignmentSavepoint(CheckingLastModifiedBTreeContainer):

	__external_can_create__ = False

	#: An :class:`.IWeakRef` to the owning user, who is probably
	#: not in our lineage.
	_owner_ref = None

	def _get_owner(self):
		return self._owner_ref() if self._owner_ref else None
	def _set_owner(self, owner):
		self._owner_ref = IWeakRef(owner)
	owner = property(_get_owner, _set_owner)

	#: A non-interface attribute for convenience (especially with early
	#: acls, since we are ICreated we get that by default)
	creator = alias('owner')

	@property
	def Items(self):
		return dict(self)

	def recordSubmission(self, submission, event=False):
		if submission.__parent__ is not None:
			raise ValueError("Objects already parented")

		item = UsersCourseAssignmentSavepointItem(Submission=submission)
		submission.__parent__ = item
		set_submission_lineage(submission)

		# check for removal
		self.removeSubmission(submission, event=event)

		if event:
			lifecycleevent.created(item)
		else:
			IConnection(self).add(item)
		self._append(submission.assignmentId, item, event=event)
		return item
	append = recordSubmission

	def removeSubmission(self, submission, event=False):
		if submission.assignmentId not in self:
			return
		item = self[submission.assignmentId]
		transfer_submission_file_data(source=item.Submission, target=submission)
		if event:
			del self[submission.assignmentId]
		else:
			self._delitemf(submission.assignmentId, event=False)
			locate(item, None, None)

	def _append(self, key, item, event=False):
		if CheckingLastModifiedBTreeContainer.__contains__(self, key):
			if item.__parent__ is self:
				return
			raise ValueError("Adding duplicate entry", item)

		if event:
			self[key] = item
		else:
			self._setitemf(key, item)
			locate(item, self, name=key)

		self.lastModified = max(self.lastModified, item.lastModified)

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.owner

		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		aces = [ace_allowing(self.owner, ALL_PERMISSIONS, type(self))]
		course = ICourseInstance(self, None)
		for instructor in getattr(course, 'instructors', ()):  # already principals
			aces.append(ace_allowing(instructor, ACT_READ, type(self)))
		aces.append(ACE_DENY_ALL)
		return acl_from_aces(aces)

@interface.implementer(IUsersCourseAssignmentSavepointItem,
					   IACLProvider,
					   ISublocations)
class UsersCourseAssignmentSavepointItem(PersistentCreatedModDateTrackingObject,
										 Contained,
										 SchemaConfigured):
	createDirectFieldProperties(IUsersCourseAssignmentSavepointItem)

	__external_can_create__ = False

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			# If the user is deleted, we will not be able to do this
			try:
				return iface(self.__parent__)
			except (AttributeError, TypeError):
				return None

	@property
	def creator(self):
		# For ACL purposes, not part of the interface
		return IUser(self, None)

	@creator.setter
	def creator(self, nv):
		# Ignored
		pass

	@property
	def assignmentId(self):
		return self.__name__

	@property
	def __acl__(self):
		aces = [ace_allowing(self.owner, ALL_PERMISSIONS,
							 UsersCourseAssignmentSavepointItem)]
		aces.append(ACE_DENY_ALL)
		return acl_from_aces(aces)

	def sublocations(self):
		if self.Submission is not None:
			yield self.Submission

@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseAssignmentSavepoints)
def _savepoints_for_course(course, create=True):
	result = None
	annotations = IAnnotations(course)
	try:
		KEY = 'AssignmentSavepoints'
		result = annotations[KEY]
	except KeyError:
		if create:
			result = UsersCourseAssignmentSavepoints()
			annotations[KEY] = result
			result.__name__ = KEY
			result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseAssignmentSavepoint)
def _savepoint_for_user_in_course(course, user, create=True):
	result = None
	savepoints = _savepoints_for_course(course)
	try:
		result = savepoints[user.username]
	except KeyError:
		if create:
			result = UsersCourseAssignmentSavepoint()
			result.owner = user
			savepoints[user.username] = result
	return result

def _savepoints_for_course_path_adapter(course, request):
	return _savepoints_for_course(course)

def _savepoints_for_courseenrollment_path_adapter(enrollment, request):
	return _savepoints_for_course(ICourseInstance(enrollment))

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentSavepointItem)
def _course_from_savepointitem_lineage(item):
	return course_from_context_lineage(item, validate=True)

@component.adapter(IUsersCourseAssignmentSavepoints, IRequest)
class _UsersCourseAssignmentSavepointsTraversable(ContainerAdapterTraversable):

	def traverse(self, key, remaining_path):
		try:
			return super(_UsersCourseAssignmentSavepointsTraversable, self).traverse(key, remaining_path)
		except LocationError:
			user = User.get_user(key)
			if user is not None:
				return _savepoint_for_user_in_course(self.context.__parent__, user)
			raise

@component.adapter(IUsersCourseAssignmentSavepoint, IRequest)
class _UsersCourseAssignmentSavepointTraversable(ContainerAdapterTraversable):

	def traverse(self, key, remaining_path):
		assesment = component.queryUtility(IQAssessment, name=key)
		if assesment is not None:
			return assesment
		raise LocationError( self.context, key )

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_savepoints_for_course(course)

def _delete_assignment_save_point(item):
	user = IUser(item, None)
	course = find_interface(item, ICourseInstance, strict=False)
	if user is not None and course is not None:
		assignment_savepoint = component.getMultiAdapter((course, user),
													 	 IUsersCourseAssignmentSavepoint)
		assignment_savepoint.removeSubmission(item.Submission, event=False)
		return True
	return False

@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectRemovedEvent)
def _on_assignment_history_item_deleted(item, event):
	_delete_assignment_save_point(item)

@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectAddedEvent)
def _on_assignment_history_item_added(item, event):
	_delete_assignment_save_point(item)
