#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 21

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.assessment import get_evaluation_catalog

from nti.assessment.interfaces import IQEvaluation

from nti.common.proxy import removeAllProxies

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IGlobalContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.intid.common import addIntId

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.hostpolicy import get_all_host_sites

from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

def _process_items(registry, intids, seen):
	site_library = component.getUtility( IContentPackageLibrary )
	if IGlobalContentPackageLibrary.providedBy(site_library):
		return

	catalog = get_evaluation_catalog()
	for name, item in list(registry.getUtilitiesFor(IQEvaluation)):
		if name in seen:
			continue
		seen.add(name)
		if item is None:
			logger.info('Empty assessment registered (%s)', name)
			unregisterUtility(registry, provided=IQEvaluation, name=name)
			continue
		item = removeAllProxies( item )
		__traceback_info__ = item
		old_parent = item.__parent__
		if old_parent is None:
			container_id = getattr(item, 'containerId', '')
			logger.info('Empty parent for (%s) (new_parent=%s)',
						 name, container_id)
			if container_id is not None:
				container = find_object_with_ntiid(container_id)
				if IContentUnit.providedBy(container):
					new_parent = container
		else:
			new_parent = find_object_with_ntiid(old_parent.ntiid)
		doc_id = None
		library = find_interface(item, IContentPackageLibrary, strict=False)
		if not IGlobalContentPackageLibrary.providedBy(library):
			# Make sure we have intid
			doc_id = intids.queryId(item)
			if doc_id is None:
				logger.info('Item without intid (%s)', item.ntiid)
				addIntId(item)

		if old_parent != new_parent:
			new_parent = removeAllProxies( new_parent )
			# These are probably locked objects that we never re-parented
			# content units on subsequent syncs.
			item.__parent__ = new_parent
			logger.info('Fixing lineage and re-indexing (%s)', item.ntiid)
			if doc_id is not None:
				catalog.index_doc(doc_id, item)

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
				_process_items(registry, intids, seen)

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 21 by updating orphaned assessments
	and indexing into correct site.
	"""
	do_evolve(context)
