#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 24

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.proxy import removeAllProxies

from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IGlobalContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.metadata import get_uid
from nti.metadata.interfaces import IMetadataQueue

from nti.site.hostpolicy import get_all_host_sites

from nti.traversal.traversal import find_interface

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

def _process_items(registry, queue, intids, seen):
	for ntiid, item in list(registry.getUtilitiesFor(IQEvaluation)):
		if not IQEditableEvaluation.providedBy(item) and ntiid not in seen:
			seen.add(ntiid)
			package = find_interface(item, IContentPackage, strict=False)
			if IGlobalContentPackage.providedBy(package):
				continue
			container = IQAssessmentItemContainer(package, None)
			if container is None:
				continue
			lastMod = container.lastModified or 0
			if not lastMod:
				continue
			item = removeAllProxies(item)
			item.lastModified = item.createdTime = lastMod
			uid = get_uid(item, intids)
			if uid is not None:
				try:
					queue.add(uid)
				except TypeError:
					pass

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']
	lsm = ds_folder.getSiteManager()
	intids = lsm.getUtility(IIntIds)
	queue = lsm.getUtility(IMetadataQueue)

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
				_process_items(registry, queue, intids, seen)
		seen.clear()

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 24 by setting the lastMod and createdTime to eval objects
	"""
	do_evolve(context)
