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

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.hostpolicy import get_all_host_sites

def _process_items(registry, intids, seen):
	catalog = get_evaluation_catalog()
	for _, item in list(registry.getUtilitiesFor(IQEvaluation)):
		if item.ntiid in seen:
			continue
		seen.add( item.ntiid )
		old_parent = item.__parent__
		new_parent = find_object_with_ntiid( old_parent.ntiid )
		if old_parent != new_parent:
			# These are probably locked objects that we never re-parented
			# on subsequent syncs.
			logger.info( 'Fixing lineage and re-indexing (%s)', item.ntiid )
			item.__parent__ = new_parent
			doc_id = intids.queryId(item)
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
