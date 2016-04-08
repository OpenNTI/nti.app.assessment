#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division


__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 19

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites

def _process_pacakge(package, intids):
	def _recur(unit):
		items = IQAssessmentItemContainer(unit)
		for ntiid, item in list(items.items()): # mutating
			provided = iface_of_assessment(item)
			registered = component.queryUtility(provided, name=ntiid)
			if registered is None:
				items.pop(ntiid, None)
				if intids.queryId(item) is not None:
					lifecycleevent.removed(item)
				item.__parent__ = None
				logger.warn("%s has been removed from container %s", 
						    ntiid, unit.ntiid)
			elif registered is not item:
				if intids.queryId(registered) is None:
					intids.register(registered)
				if registered.__parent__ is None:
					registered.__parent__ = unit
				# update container
				items.pop(ntiid, None)
				items[ntiid] = registered
				# update indices
				lifecycleevent.modified(registered)
				logger.warn("%s has been updated in container %s", 
						    ntiid, unit.ntiid)
		for child in unit.children or ():
			_recur(child)
	_recur(package)
	
def _process_registry(registry, intids, seen):
	for package in yield_sync_content_packages():
		if package.ntiid not in seen:
			seen.add(package.ntiid)
			_process_pacakge(package, intids)

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

		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		seen = set()
		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()
				_process_registry(registry, intids, seen)

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 20 by updating the AssessmentItemContainer for content units
	with the registered objects
	"""
	do_evolve(context)
