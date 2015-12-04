#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component

from zope.location.interfaces import ILocationInfo

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contentlibrary.externalization import root_url_of_unit
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from ..common import get_course_from_assignment

class _AbstractTraversableLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		# We only do this if we can create the traversal path to this object;
		# many times the CourseInstanceEnrollments aren't fully traversable
		# (specifically, for the course roster)
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			if context.__parent__ is None:
				return False # Short circuit
			try:
				loc_info = ILocationInfo( context )
				loc_info.getParents()
			except TypeError:
				return False
			else:
				return True

def _get_course_from_assignment(assignment, user=None, catalog=None, registry=component):
	return get_course_from_assignment(assignment=assignment,
									  user=user,
									  catalog=catalog,
									  registry=registry)

def _root_url(ntiid):
	library = component.queryUtility(IContentPackageLibrary)
	if ntiid and library is not None:
		paths = library.pathToNTIID(ntiid)
		package = paths[0] if paths else None
		try:
			result = root_url_of_unit(package) if package is not None else None
			return result
		except Exception:
			pass
	return None
