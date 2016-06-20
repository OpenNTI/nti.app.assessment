#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 25

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from nti.assessment.interfaces import IQPoll 
from nti.assessment.interfaces import IQuestion 
from nti.assessment.interfaces import IQAssignment

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites

@interface.implementer(IDataserver)
class MockDataserver(object):

	root = None

	def get_by_oid(self, oid, ignore_creator=False):
		resolver = component.queryUtility(IOIDResolver)
		if resolver is None:
			logger.warn("Using dataserver without a proper ISiteManager configuration.")
		else:
			return resolver.get_object_by_oid(oid, ignore_creator=ignore_creator)
		return None

def _process_items(registry, seen):
	for provied in (IQuestion, IQPoll):
		for ntiid, item in list(registry.getUtilitiesFor(provied)):
			if ntiid in seen:
				continue
			seen.add(ntiid)
			try:
				for part in item.parts or ():
					getattr(part, 'ntiid', None) # force set
					for s in getattr(part, 'solutions', None) or ():
						s.__parent__ = part
			except AttributeError:
				pass
	for ntiid, item in list(registry.getUtilitiesFor(IQAssignment)):
		if ntiid in seen:
			continue
		seen.add(ntiid)
		[part.ntiid for part in item.parts or ()]  # force set

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	with current_site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		# Load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		seen = set()
		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()
				_process_items(registry, seen)
				
		logger.info("%s item(s) processed", len(seen))
		seen.clear()

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 25 by setting lineage for solutions
	"""
	do_evolve(context)
