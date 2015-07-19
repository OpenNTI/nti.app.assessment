#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .. import MessageFactory

from zope import component
from zope.component.interfaces import ComponentLookupError

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.ntiids.ntiids import find_object_with_ntiid

from .._utils import assignment_download_precondition

def parse_catalog_entry(params, names=('ntiid', 'entry', 'course')):
	ntiid = None
	for name in names:
		ntiid = params.get(name)
		if ntiid:
			break
	if not ntiid:
		return None

	context = find_object_with_ntiid(ntiid)
	result = ICourseCatalogEntry(context, None)
	if result is None:
		try:
			catalog = component.getUtility(ICourseCatalog)
			result = catalog.getCatalogEntry(ntiid)
		except (KeyError, ComponentLookupError):
			pass
	return result
