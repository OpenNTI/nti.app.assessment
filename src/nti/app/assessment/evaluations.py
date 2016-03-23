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

from zope.lifecycleevent.interfaces import IObjectAddedEvent

from pyramid.interfaces import IRequest

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_editors

from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.traversal.traversal import find_interface

@interface.implementer(ICourseEvaluations)
class CourseEvaluations(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course evaluations.
	"""

	__external_can_create__ = False

	@property
	def Items(self):
		return dict(self)

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
		aces.append(ACE_DENY_ALL)
		result = acl_from_aces(aces)
		return result

@component.adapter(ICourseInstance)
@interface.implementer(ICourseEvaluations)
def _evaluations_for_course(course, create=True):
	result = None
	annotations = IAnnotations(course)
	try:
		KEY = 'CourseEvaluations'
		result = annotations[KEY]
	except KeyError:
		if create:
			result = CourseEvaluations()
			annotations[KEY] = result
			result.__name__ = KEY
			result.__parent__ = course
	return result

@component.adapter(ICourseInstance, IRequest)
def _evaluations_for_course_path_adapter(course, request):
	return _evaluations_for_course(course)

@interface.implementer(ICourseInstance)
@component.adapter(ICourseEvaluations)
def _course_from_item_lineage(item):
	return course_from_context_lineage(item, validate=True)

@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, event):
	_evaluations_for_course(course)
