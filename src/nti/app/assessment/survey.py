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

from zope.annotation.interfaces import IAnnotations

from zope.container.contained import Contained

from zope.lifecycleevent.interfaces import IObjectAddedEvent

from zope.location.interfaces import LocationError
from zope.location.interfaces import ISublocations

from zope.security.interfaces import IPrincipal

from pyramid.interfaces import IRequest

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAggregatedSurvey

from nti.common.property import alias
from nti.common.property import readproperty

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments

from nti.dataserver.users import User

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS
from nti.dataserver.interfaces import EVERYONE_USER_NAME

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.externalization.interfaces import StandardExternalFields

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable

from nti.wref.interfaces import IWeakRef

from ._submission import set_inquiry_submission_lineage

from .common import get_course_inquiries

from .interfaces import IUsersCourseInquiry
from .interfaces import ICourseInquiryCatalog
from .interfaces import IUsersCourseInquiries
from .interfaces import IUsersCourseInquiryItem
from .interfaces import ICourseAggregatedSurveys

LINKS = StandardExternalFields.LINKS

@interface.implementer(IUsersCourseInquiries)
class UsersCourseInquiries(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course inquirys for all users in a course.
	"""

@interface.implementer(IUsersCourseInquiry)
class UsersCourseInquiry(CheckingLastModifiedBTreeContainer):
	
	__external_can_create__ = False

	#: An :class:`.IWeakRef` to the owning user
	_owner_ref = None

	def _get_owner(self):
		return self._owner_ref() if self._owner_ref else None
	def _set_owner(self,owner):
		self._owner_ref = IWeakRef(owner)
	owner = property(_get_owner,_set_owner)

	creator = alias('owner')

	@property
	def Items(self):
		return dict(self)
	
	def recordSubmission(self, submission):
		if submission.__parent__ is not None:
			raise ValueError("Objects already parented")
		
		item = UsersCourseInquiryItem(Submission=submission)
		submission.__parent__ = item
		set_inquiry_submission_lineage(submission)
		
		self[submission.id] = item
		return item

	def removeSubmission(self, submission):
		inquiryId = getattr(submission, 'id', str(submission))
		if inquiryId not in self:
			return
		del self[inquiryId]

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.owner

		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing( self.owner, ACT_READ, UsersCourseInquiry )]
		for instructor in instructors:
			aces.append( ace_allowing(instructor, ALL_PERMISSIONS, UsersCourseInquiry) )
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

@interface.implementer(IUsersCourseInquiryItem,
					   IACLProvider,
					   ISublocations)
class UsersCourseInquiryItem(PersistentCreatedModDateTrackingObject,
				             Contained,
						     SchemaConfigured):
	createDirectFieldProperties(IUsersCourseInquiryItem)

	__external_can_create__ = False

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			try:
				return iface(self.__parent__)
			except (AttributeError, TypeError):
				return None

	@property
	def creator(self):
		return IUser(self, None)

	@creator.setter
	def creator(self, nv):
		pass

	@property
	def inquiryId(self):
		return self.__name__

	@readproperty
	def Inquiry(self):
		result = component.queryUtility(IQInquiry, name=self.__name__)
		return result

	@property
	def __acl__(self):
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing( self.creator, ACT_READ, UsersCourseInquiryItem )]
		for instructor in instructors:
			aces.append( ace_allowing(instructor, ALL_PERMISSIONS, UsersCourseInquiryItem) )
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

	def sublocations(self):
		if self.Submission is not None:
			yield self.Submission

@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseInquiries)
def _inquiries_for_course(course, create=True):
	result = None
	annotations = IAnnotations(course)
	try:
		KEY = 'Inquiries'
		result = annotations[KEY]
	except KeyError:
		if create:
			result = UsersCourseInquiries()
			annotations[KEY] = result
			result.__name__ = KEY
			result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseInquiry)
def _inquiry_for_user_in_course(course, user, create=True):
	result = None
	inquirys = _inquiries_for_course(course)
	try:
		result = inquirys[user.username]
	except KeyError:
		if create:
			result = UsersCourseInquiry()
			result.owner = user
			inquirys[user.username] = result
	return result

def _inquiries_for_course_path_adapter(course, request):
	return _inquiries_for_course(course)

def _inquiries_for_courseenrollment_path_adapter(enrollment, request):
	return _inquiries_for_course( ICourseInstance(enrollment) )

from .adapters import _course_from_context_lineage

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseInquiryItem)
def _course_from_inquiryitem_lineage(item):
	return _course_from_context_lineage(item)

@component.adapter(IUsersCourseInquiries, IRequest)
class _UsersCourseInquiriesTraversable(ContainerAdapterTraversable):

	def traverse( self, key, remaining_path ):
		try:
			return super(_UsersCourseInquiriesTraversable, self).traverse(key, remaining_path)
		except LocationError:
			user = User.get_user(key)
			if user is not None:
				return _inquiry_for_user_in_course( self.context.__parent__, user)			
			raise		

@interface.implementer(ICourseInstance)
@component.adapter(IQInquiry, IUser)
def _course_from_inquiry_lineage(inquiry, user):
	"""
	Given a generic inquiry and a user, we attempt to associate the inquiry with the most
	specific course instance relevant for the user.

	In more sophisticated cases involving sections, the assumption that a course instance 
	is one-to-one with a contentpackage is broken. In that case, it's better to try to 
	look through the things the user is enrolled in and try to match the content
	package to the first course.
	"""

	package = find_interface(inquiry, IContentPackage, strict=False)
	if package is None:
		return None

	catalog = component.queryUtility(ICourseCatalog)
	if catalog is None:
		return

	prin = IPrincipal(user)
	for entry in catalog.iterCatalogEntries():
		course = ICourseInstance(entry)
		if package in course.ContentPackageBundle.ContentPackages:
			## Ok, found one. Are we enrolled or an instructor?
			if prin in course.instructors:
				return course
			
			enrollments = ICourseEnrollments(course)
			if enrollments.get_enrollment_for_principal(user) is not None:
				return course

	## No current course matches. Fall back and check all your enrollments.
	for enrollments in component.subscribers( (user,), IPrincipalEnrollments):
		for enrollment in enrollments.iter_enrollments():
			course = ICourseInstance(enrollment)
			if package in course.ContentPackageBundle.ContentPackages:
				return course

			enrollments = ICourseEnrollments(course)
			if ICourseEnrollments(course).get_enrollment_for_principal(user) is not None:
				return course
	
@interface.implementer(ICourseInquiryCatalog)
@component.adapter(ICourseInstance)
class _DefaultCourseInquiryCatalog(object):

	def __init__(self, context):
		self.context = context
	
	def iter_inquiries(self):
		result = get_course_inquiries(self.context)
		return result

@interface.implementer(ICourseAggregatedSurveys)
class CourseAggregatedSurveys(CheckingLastModifiedBTreeContainer):
	
	__external_can_create__ = False
	
	def __conform__(self, iface):
		if ICourseInstance.isOrExtends(iface):
			return self.__parent__
		
	@property
	def __acl__(self):
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing(i, ALL_PERMISSIONS, CourseAggregatedSurveys) 
				for i in instructors]
		aces.append(ace_allowing(EVERYONE_USER_NAME, ACT_READ))
		return acl_from_aces( aces )
	
@component.adapter(ICourseInstance)
@interface.implementer(ICourseAggregatedSurveys)
def _aggreated_inquiries_for_course(course):
	annotations = IAnnotations(course)
	try:
		KEY = 'AggregatedInquiries'
		result = annotations[KEY]
	except KeyError:
		result = CourseAggregatedSurveys()
		annotations[KEY] = result
		result.__name__ = KEY
		result.__parent__ = course
	return result

def _aggreated_inquiries_for_course_path_adapter(course, request):
	return _aggreated_inquiries_for_course(course)

def _aggreated_inquiries_for_courseenrollment_path_adapter(enrollment, request):
	return _aggreated_inquiries_for_course( ICourseInstance(enrollment) )

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_inquiries_for_course(course)

@component.adapter(IUsersCourseInquiryItem, IObjectAddedEvent)
def _on_course_inquiry_item_added(item, event):
	pass

def aggregate_survey_submission(storage, submission):
	aggregated_inquiry = IQAggregatedSurvey(submission)
	for aggregated_poll in aggregated_inquiry.questions:
		pollId = aggregated_poll.pollId
		if pollId not in storage:
			storage[pollId] = aggregated_poll
		else:
			stored = storage[pollId]
			stored += aggregated_poll
