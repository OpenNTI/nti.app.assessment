#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 30.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 31

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.assessment import get_evaluation_catalog

from nti.app.assessment.index import IX_CONTAINERS

from nti.assessment.interfaces import IQEvaluation

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

def _update_evaluation_index( registry, container_index, intids, seen ):
	count = 0
	for ntiid, item in list(registry.getUtilitiesFor(IQEvaluation)):
		if ntiid not in seen:
			seen.add( ntiid )
			doc_id = intids.queryId(item)
			if doc_id is not None:
				container_index.index_doc( doc_id, item )
				count +=1
	return count

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

		catalog = get_evaluation_catalog()
		container_index = catalog[IX_CONTAINERS]
		seen = set()
		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()
				count = _update_evaluation_index(registry, container_index, intids, seen)
				logger.info( '[%s] Indexed %s objects', site.__name__, count )

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 31 by re-indexing evaluation objects in the
	container index in order to make sure all course/packages are correct.
	"""
	do_evolve(context)
