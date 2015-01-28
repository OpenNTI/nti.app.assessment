#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 2.

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 2

from zope import component
from zope.component.hooks import site as current_site

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
		
def iter_courses(dataserver_folder):
	seen = set()
	sites = dataserver_folder['++etc++hostsites']
	for site in sites.values():
		with current_site(site):
			catalog = component.getUtility(ICourseCatalog)
			for entry in catalog.iterCatalogEntries():
				course = ICourseInstance(entry, None)
				if course is not None and entry.ntiid not in seen:
					seen.add(entry.ntiid)
					yield entry, course

def evolve(context):
	"""
	Evolve to generation 2
	"""
	pass
