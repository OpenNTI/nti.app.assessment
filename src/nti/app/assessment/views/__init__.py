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

from pyramid.threadlocal import get_current_request

from nti.app.assessment.common import can_disclose_inquiry

from nti.app.assessment.utils import assignment_download_precondition

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.ntiids.ntiids import find_object_with_ntiid

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

def get_ds2(request=None):
	request = request if request else get_current_request()
	try:
		return request.path_info_peek() if request else None  # e.g. /dataserver2
	except AttributeError:  # in unit test we may see this
		return "dataserver2"
