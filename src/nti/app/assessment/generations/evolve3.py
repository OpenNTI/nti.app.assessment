#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 3.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 3

import zope.intid

from zope import component
from zope import interface

from zope.component.hooks import site, setHooks

from zope.catalog.interfaces import ICatalog

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver
from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.site.hostpolicy import run_job_in_all_host_sites

from nti.zope_catalog.catalog import ResultSet

from ..index import install_assesment_catalog

from ..interfaces import IUsersCourseAssignmentHistories

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

def fix_history_lineage():
	catalog = component.queryUtility(ICourseCatalog)
	if catalog is None:
		return
	# In Janux we saw some some UsersCourseAssignmentHistoryItem objects
	# with incorrect __parent__ attribute.
	for entry in catalog.iterCatalogEntries():
		course = ICourseInstance(entry)
		histories = IUsersCourseAssignmentHistories(course)
		if histories.__parent__ != course:
			histories.__parent__ = course
		for history in histories.values():
			if history.__parent__ != histories:
				history.__parent__ = histories	

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']
	lsm = ds_folder.getSiteManager()
	intids = lsm.getUtility(zope.intid.IIntIds)

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	with site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		total = 0
		metadata_catalog = lsm.getUtility(ICatalog, METADATA_CATALOG_NAME)
		assesment_catalog = install_assesment_catalog(ds_folder, intids)

		# load libray
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		fix_history_lineage()
		run_job_in_all_host_sites(fix_history_lineage)
	
		# index all history items
		MIME_TYPES = ('application/vnd.nextthought.assessment.userscourseassignmenthistoryitem',
					  'application/vnd.nextthought.assessment.userscourseinquiryitem')
		item_intids = metadata_catalog['mimeType'].apply({'any_of': MIME_TYPES})
		results = ResultSet(item_intids, intids, True)
		for uid, obj in results.iter_pairs():
			try:
				assesment_catalog.force_index_doc(uid, obj)
				total += 1
			except Exception:
				logger.debug("Cannot index object with id %s", uid)

		logger.info('Assessment evolution %s done; %s items(s) indexed',
					generation, total)

def evolve(context):
	"""
	Evolve to generation 3 by installing an assessment index
	"""
	do_evolve(context)
