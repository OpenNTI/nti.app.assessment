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

from pyramid.interfaces import IRequest

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.interfaces import ICourseEvaluationEditionRecord
from nti.app.assessment.interfaces import ICourseEvaluationEditionRecords

from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_editors

from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.traversal.traversal import find_interface

@interface.implementer(ICourseEvaluationEditionRecords)
class CourseEvaluationEditionRecords(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course evaluation edition records in a course.
	"""

	__external_can_create__ = False

	@property
	def Items(self):
		return dict(self)

	def __conform__(self, iface):
		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		aces = [ ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, self),
				 ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
		course = find_interface(self.context, ICourseInstance, strict=False)
		if course is not None:
			aces.extend(ace_allowing(i, ALL_PERMISSIONS, type(self))
						for i in course.instructors)
			aces.extend(ace_allowing(i, ALL_PERMISSIONS, type(self))
						for i in get_course_editors(course))
		result = acl_from_aces(aces)
		return result

@component.adapter(ICourseInstance)
@interface.implementer(ICourseEvaluationEditionRecords)
def _evaluation_editions_for_course(course, create=True):
	result = None
	annotations = IAnnotations(course)
	try:
		KEY = 'CourseEvaluationEditions'
		result = annotations[KEY]
	except KeyError:
		if create:
			result = CourseEvaluationEditionRecords()
			annotations[KEY] = result
			result.__name__ = KEY
			result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IRequest)
def _evaluation_editions_for_course_path_adapter(course, request):
	return _evaluation_editions_for_course(course)

@interface.implementer(ICourseInstance)
@component.adapter(ICourseEvaluationEditionRecords)
def _course_from_item_lineage(item):
	return course_from_context_lineage(item, validate=True)

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_evaluation_editions_for_course(course)

@interface.implementer(ICourseEvaluationEditionRecord)
class CourseEvaluationEditionRecord(PersistentCreatedModDateTrackingObject,
									SchemaConfigured,
									Contained):
	createDirectFieldProperties(ICourseEvaluationEditionRecord)

	@property
	def assessmentId(self):
		return self.__name__
	evaluationId = assessmentId
