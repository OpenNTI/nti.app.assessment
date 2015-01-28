#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope.component import ComponentLookupError

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

class _ContextCatalogEntryDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		return bool(self._is_authenticated)
	
	def _do_decorate_external(self, context, result):
		try:
			course = ICourseInstance(context, None)
			entry = ICourseCatalogEntry(course, None)
			if entry is not None:
				result['CatalogEntryNTIID'] = entry.ntiid
		except ComponentLookupError:
			pass
