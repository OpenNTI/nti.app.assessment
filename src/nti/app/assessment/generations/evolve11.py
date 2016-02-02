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

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.intid.interfaces import IIntIds

from zope.location.location import locate

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import SiteIndex
from nti.app.assessment.index import CatalogEntryIDIndex
from nti.app.assessment.index import install_assesment_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']
	lsm = ds_folder.getSiteManager()
	intids = lsm.getUtility(IIntIds)

	with site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		from IPython.core.debugger import Tracer; Tracer()()
		assesment_catalog = install_assesment_catalog(ds_folder, intids)
		
		if IX_SITE not in assesment_catalog:
			site_index = SiteIndex(family=intids.family)
			intids.register(site_index)
			locate(site_index, assesment_catalog, IX_SITE)
			assesment_catalog[IX_SITE] = site_index
		else:
			site_index = assesment_catalog[IX_SITE]
	
		# replace catlog entry index
		old_index = assesment_catalog[IX_COURSE]
		if not isinstance(old_index, CatalogEntryIDIndex):
			intids.unregister(old_index)
			del assesment_catalog[IX_COURSE]
			locate(old_index, None, None)

			new_index = CatalogEntryIDIndex(family=intids.family)
			intids.register(new_index)
			locate(new_index, assesment_catalog, IX_COURSE)
			assesment_catalog[IX_COURSE] = new_index

			for doc_id in old_index.ids():
				obj = intids.queryObject(doc_id)
				if 	(	IUsersCourseInquiryItem.providedBy(obj)
					 or	IUsersCourseAssignmentHistoryItem.providedBy(obj)):
					new_index.index_doc(doc_id, obj)
					site_index.index_doc(doc_id, obj)

			# clear old
			old_index.clear()

		logger.info('Assessment evolution %s done', generation)

def evolve(context):
	"""
	Evolve to generation 11 by replacing the course index and add site index
	"""
	do_evolve(context)
