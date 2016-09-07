#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import lifecycleevent

from zope.location.location import locate

from ZODB.interfaces import IConnection

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

	def _save(self, key, value):
		self._setitemf(key, value)
		locate(value, parent=self, name=key)
		if IConnection(value, None) is None:
			IConnection(self).add(value)
		lifecycleevent.added(value, self, key)
		self.updateLastMod()
		self._p_changed = True

	def __setitem__(self, key, value):
		self._save(key, value)

	def _eject(self, key):
		self._delitemf(key)
		self.updateLastMod()
		self._p_changed = True

	def __delitem__(self, key):
		self._eject(key)

	def replace(self, old, new):
		assert old.ntiid == new.ntiid
		ntiid = old.ntiid
		self._eject(ntiid)
		self._save(ntiid, new)
		return new

	@property
	def __acl__(self):
		aces = [ ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, self),
				 ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
		course = find_interface(self.context, ICourseInstance, strict=False)
		if course is not None:
			aces.extend(ace_allowing(i, ALL_PERMISSIONS, type(self))
						for i in course.instructors or ())
			aces.extend(ace_allowing(i, ALL_PERMISSIONS, type(self))
						for i in get_course_editors(course))
		aces.append(ACE_DENY_ALL)
		result = acl_from_aces(aces)
		return result
