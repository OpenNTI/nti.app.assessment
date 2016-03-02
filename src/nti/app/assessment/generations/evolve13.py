#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 13

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.assessment.interfaces import IQSubmittable

from nti.coremetadata.interfaces import IPublishable

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.metadata import metadata_queue

from nti.site.hostpolicy import get_all_host_sites

def _process_items(registry, intids, seen):
	queue = metadata_queue()
	for ntiid, item in list(registry.getUtilitiesFor(IQSubmittable)):
		if ntiid in seen:
			continue
		seen.add(ntiid)
		if IPublishable.providedBy(item) and not item.is_published():
			item.publish()
			doc_id = intids.queryId(item)
			if doc_id is not None:
				try:
					queue.add(doc_id)
				except TypeError:
					pass

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
	logger.info('Assessment evolution %s done', generation)

def evolve(context):
	"""
	Evolve to generation 13 by publishing assesments
	"""
	do_evolve(context)
