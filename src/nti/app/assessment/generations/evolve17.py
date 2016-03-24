#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 17

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.assessment.index import install_evaluation_catalog

from nti.assessment.interfaces import IQEvaluation

from nti.contentlibrary.indexed_data import get_library_catalog

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

def _process_items(registry, eval_catalog, lib_catalog, intids, seen):
	for _, item in list(registry.getUtilitiesFor(IQEvaluation)):
		doc_id = intids.queryId(item)
		if doc_id is not None and doc_id not in seen:
			seen.add(doc_id)
			lib_catalog.unindex_doc(doc_id)
			eval_catalog.index_doc(doc_id, item)

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']
	lsm = ds_folder.getSiteManager()
	intids = lsm.getUtility(IIntIds)

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	seen = set()
	with site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		eval_catalog = install_evaluation_catalog(ds_folder, intids)
		lib_catalog = get_library_catalog()
		
		# Load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()
				_process_items(registry,
							   eval_catalog, 
							   lib_catalog,
							   intids,
							   seen)

		component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
		logger.info('Assessment evolution %s done. %s items indexed', 
					generation, len(seen))

def evolve(context):
	"""
	Evolve to generation 17 by registering the evaluation catalog
	"""
	do_evolve(context, generation)
