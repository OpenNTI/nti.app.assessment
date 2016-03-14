#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 11

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.intid.interfaces import IIntIds

from zope.location.location import locate

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import SiteIndex
from nti.app.assessment.index import CatalogEntryIDIndex
from nti.app.assessment.index import install_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

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

	with site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		# load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		submission_catalog = install_submission_catalog(ds_folder, intids)

		if IX_SITE not in submission_catalog:
			site_index = SiteIndex(family=intids.family)
			intids.register(site_index)
			locate(site_index, submission_catalog, IX_SITE)
			submission_catalog[IX_SITE] = site_index
		else:
			site_index = submission_catalog[IX_SITE]

		# replace catlog entry index
		old_index = submission_catalog[IX_COURSE]
		if not isinstance(old_index, CatalogEntryIDIndex):
			intids.unregister(old_index)
			del submission_catalog[IX_COURSE]
			locate(old_index, None, None)

			new_index = CatalogEntryIDIndex(family=intids.family)
			intids.register(new_index)
			locate(new_index, submission_catalog, IX_COURSE)
			submission_catalog[IX_COURSE] = new_index

			for doc_id in old_index.ids():
				obj = intids.queryObject(doc_id)
				if 	(IUsersCourseInquiryItem.providedBy(obj)
					 or	IUsersCourseAssignmentHistoryItem.providedBy(obj)):
					new_index.index_doc(doc_id, obj)
					site_index.index_doc(doc_id, obj)

			# clear old
			old_index.clear()

		component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
		logger.info('Assessment evolution %s done', generation)

def evolve(context):
	"""
	Evolve to generation 11 by replacing the course index and add site index
	"""
	do_evolve(context)
