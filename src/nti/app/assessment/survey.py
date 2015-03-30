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

from zope.security.interfaces import IPrincipal

from zope.location.location import locate
from zope.location.interfaces import LocationError
from zope.location.interfaces import ISublocations

from ZODB.interfaces import IConnection

from pyramid.interfaces import IRequest

from nti.assessment.interfaces import IQSurvey

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

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.externalization.interfaces import StandardExternalFields

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable

from nti.wref.interfaces import IWeakRef

from ._submission import set_submission_lineage

from .interfaces import IUsersCourseSurvey
from .interfaces import IUsersCourseSurveys
from .interfaces import IUsersCourseSurveyItem

LINKS = StandardExternalFields.LINKS

@interface.implementer(IUsersCourseSurveys)
class UsersCourseSurveys(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course surveys for all users in a course.
	"""

@interface.implementer(IUsersCourseSurvey)
class UsersCourseSurvey(CheckingLastModifiedBTreeContainer):
	
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
	
	def recordSubmission(self, submission, event=False):
		if submission.__parent__ is not None:
			raise ValueError("Objects already parented")
		
		item = UsersCourseSurveyItem(Submission=submission)
		submission.__parent__ = item
		set_submission_lineage(submission)
		
		# check for removal
		self.removeSubmission(submission, event=event)
		if event:
			lifecycleevent.created(item)
		else:
			IConnection(self).add(item)
		self._append(submission.surveyId, item, event=event)
		return item

	def removeSubmission(self, submission, event=False):
		if submission.surveyId not in self:
			return
		item = self[submission.surveyId]
		if event:
			del self[submission.surveyId]
		else:
			self._delitemf(submission.surveyId, event=False)
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

		self.lastModified = max( self.lastModified, item.lastModified )
		
	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.owner

		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing( self.owner, ACT_READ, UsersCourseSurvey )]
		for instructor in instructors:
			aces.append( ace_allowing(instructor, ALL_PERMISSIONS, UsersCourseSurvey) )
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

@interface.implementer(IUsersCourseSurveyItem,
					   IACLProvider,
					   ISublocations)
class UsersCourseSurveyItem(PersistentCreatedModDateTrackingObject,
				            Contained,
						    SchemaConfigured):
	createDirectFieldProperties(IUsersCourseSurveyItem)

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
	def surveyId(self):
		return self.__name__

	@readproperty
	def Survey(self):
		result = component.queryUtility(IQSurvey, name=self.__name__)
		return result

	@property
	def __acl__(self):
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing( self.creator, ACT_READ, UsersCourseSurveyItem )]
		for instructor in instructors:
			aces.append( ace_allowing(instructor, ALL_PERMISSIONS, UsersCourseSurveyItem) )
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

	def sublocations(self):
		if self.Submission is not None:
			yield self.Submission

@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseSurveys)
def _surveys_for_course(course):
	annotations = IAnnotations(course)
	try:
		KEY = 'Surveys'
		result = annotations[KEY]
	except KeyError:
		result = UsersCourseSurveys()
		annotations[KEY] = result
		result.__name__ = KEY
		result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseSurvey)
def _survey_for_user_in_course(course, user, create=True):
	result = None
	surveys = _surveys_for_course(course)
	try:
		result = surveys[user.username]
	except KeyError:
		if create:
			result = UsersCourseSurvey()
			result.owner = user
			surveys[user.username] = result
	return result

def _surveys_for_course_path_adapter(course, request):
	return _surveys_for_course(course)

def _surveys_for_courseenrollment_path_adapter(enrollment, request):
	return _surveys_for_course( ICourseInstance(enrollment) )

from .adapters import _course_from_context_lineage

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseSurveyItem)
def _course_from_surveyitem_lineage(item):
	return _course_from_context_lineage(item, validate=True)

@component.adapter(IUsersCourseSurveys, IRequest)
class _UsersCourseSurveysTraversable(ContainerAdapterTraversable):

	def traverse( self, key, remaining_path ):
		try:
			return super(_UsersCourseSurveysTraversable, self).traverse(key, remaining_path)
		except LocationError:
			user = User.get_user(key)
			if user is not None:
				return _survey_for_user_in_course( self.context.__parent__, user)			
			raise		

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_surveys_for_course(course)

@interface.implementer(ICourseInstance)
@component.adapter(IQSurvey, IUser)
def _course_from_survey_lineage(survey, user):
	"""
	Given a generic survey and a user, we attempt to associate the survey with the most
	specific course instance relevant for the user.

	In more sophisticated cases involving sections, the assumption that a course instance 
	is one-to-one with a contentpackage is broken. In that case, it's better to try to 
	look through the things the user is enrolled in and try to match the content
	package to the first course.
	"""

	package = find_interface(survey, IContentPackage, strict=False)
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
