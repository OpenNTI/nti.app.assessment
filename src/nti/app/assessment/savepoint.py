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
from zope.container.contained import Contained
from zope.location.interfaces import ISublocations
from zope.annotation.interfaces import IAnnotations

from ZODB.interfaces import IConnection

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.links import Link
from nti.dataserver.links_external import render_link


from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator
from nti.externalization.externalization import to_external_ntiid_oid

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.utils.property import alias

from ._utils import set_submission_lineage
from ._utils import transfer_upload_ownership

from .decorators import _get_course_from_assignment

from .interfaces import IUsersCourseAssignmentSavepoint
from .interfaces import IUsersCourseAssignmentSavepoints
from .interfaces import IUsersCourseAssignmentSavepointItem

LINKS = StandardExternalFields.LINKS

@interface.implementer(IUsersCourseAssignmentSavepoints)
class UsersCourseAssignmentSavepoints(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course assignment save points for all users in a course.
	"""

@interface.implementer(IUsersCourseAssignmentSavepoint)
class UsersCourseAssignmentSavepoint(CheckingLastModifiedBTreeContainer):
	
	__external_can_create__ = False

	#: An :class:`.IWeakRef` to the owning user, who is probably
	#: not in our lineage.
	_owner_ref = None

	#: A non-interface attribute for convenience (especially with early
	#: acls, since we are ICreated we get that by default)
	owner = creator = alias('__parent__')

	@property
	def Items(self):
		return dict(self)
	
	def recordSubmission(self, submission):
		if submission.__parent__ is not None:
			raise ValueError("Objects already parented")

		item = UsersCourseAssignmentSavepointItem(Submission=submission)
		submission.__parent__ = item
		set_submission_lineage(submission)
		
		if submission.assignmentId in self:
			old = self[submission.assignmentId].Submission
			transfer_upload_ownership(submission, old)
			del self[submission.assignmentId]

		lifecycleevent.created(item)
		self[submission.assignmentId] = item
		return item

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		aces = [ace_allowing(self.creator, ALL_PERMISSIONS, UsersCourseAssignmentSavepoint)]
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

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
			except (AttributeError,TypeError):
				return None

	@property
	def creator(self):
		# For ACL purposes, not part of the interface
		return IUser(self, None)

	@creator.setter
	def creator(self, nv):
		pass

	@property
	def assignmentId(self):
		return self.__name__

	@property
	def __acl__(self):
		aces = [ace_allowing(self.creator, ALL_PERMISSIONS, UsersCourseAssignmentSavepointItem)]
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

	def sublocations(self):
		if self.Submission is not None:
			yield self.Submission

BASE_KEY = 'AssignmentSavepoints'
def _user_savepoint_course_key(course):
	entry = ICourseCatalogEntry(course)
	result = BASE_KEY + '_%s' % entry.ntiid
	return result

@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseAssignmentSavepoint)
def _savepoint_for_user_in_course(course, user, create=True):
	annotations = IAnnotations(user)
	key = _user_savepoint_course_key(course)
	try:
		result = annotations[key]
	except KeyError:
		if create:
			result = UsersCourseAssignmentSavepoint()
			result.__name__ = key
			result.__parent__ = user
			annotations[key] = result
			IConnection(user).add(result)
	return result

class _AssignmentSavepointDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, assignment, result):
		course = _get_course_from_assignment(assignment, self.remoteUser)
		if course is not None:
			links = result.setdefault(LINKS, [])
			links.append( Link( assignment,
								rel='Savepoint',
								elements=('Savepoint',)))

@interface.implementer(IExternalMappingDecorator)
class _AssignmentSavepointItemDecorator(AbstractAuthenticatedRequestAwareDecorator):
	
	def _predicate(self, context, result):
		creator = context.creator
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
				and creator is not None
				and creator == self.remoteUser)
		
	def _do_decorate_external(self, context, result_map ):
		try:
			link = Link(to_external_ntiid_oid(context))
			result_map['href'] = render_link( link )['href']
		except (KeyError, ValueError, AssertionError):
			pass # Nope
