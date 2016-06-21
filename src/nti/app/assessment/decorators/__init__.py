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

from pyramid.threadlocal import get_current_request

from nti.app.assessment.common import get_course_from_evaluation

from nti.app.assessment.utils import get_course_from_request

from nti.app.products.courseware.utils import PreviewCourseAccessPredicateDecorator

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contentlibrary.externalization import root_url_of_unit
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

class _AbstractTraversableLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		# We only do this if we can create the traversal path to this object;
		# many times the CourseInstanceEnrollments aren't fully traversable
		# (specifically, for the course roster)
		if self._is_authenticated:
			if context.__parent__ is None:
				return False  # Short circuit
			try:
				loc_info = ILocationInfo(context)
				loc_info.getParents()
			except TypeError:
				return False
			else:
				return True

	_is_traversable = _predicate

class AbstractAssessmentDecoratorPredicate(PreviewCourseAccessPredicateDecorator,
										   _AbstractTraversableLinkDecorator):
	"""
	Only decorate assessment items if we are preview-safe, traversable and authenticated.
	"""

	def _predicate(self, context, result):
		return 	super(AbstractAssessmentDecoratorPredicate,self)._predicate( context, result ) \
			and self._is_traversable( context, result )

def _get_course_from_evaluation(evaluation, user=None, catalog=None, request=None):
	result = None
	request = get_current_request() if request is None else request
	if request is not None:
		result = get_course_from_request(request)
	if result is None:
		result = get_course_from_evaluation(evaluation=evaluation,
									  		user=user,
									 		catalog=catalog)
	return result
_get_course_from_assignment = _get_course_from_evaluation # BWC

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
