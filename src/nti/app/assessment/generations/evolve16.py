#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 16

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.intid.interfaces import IIntIds

from zope.location.location import locate

from nti.app.assessment.index import IX_SUBMITTED
from nti.app.assessment.index import IX_ASSESSMENT_ID
from nti.app.assessment.index import AssesmentSubmittedIndex
from nti.app.assessment.index import install_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

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

		submission_catalog = install_submission_catalog(ds_folder, intids)
		if IX_SUBMITTED in submission_catalog:
			return

		index = AssesmentSubmittedIndex(family=intids.family)
		intids.register(index)
		locate(index, submission_catalog, IX_SUBMITTED)
		submission_catalog[IX_SUBMITTED] = index

		# replace catlog entry index
		source = submission_catalog[IX_ASSESSMENT_ID]
		for doc_id in source.ids():
			obj = intids.queryObject(doc_id)
			if 		IUsersCourseInquiryItem.providedBy(obj) \
				or	IUsersCourseAssignmentHistoryItem.providedBy(obj):
					index.index_doc(doc_id, obj)

		component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
		logger.info('Assessment evolution %s done', generation)
def evolve(context):
	"""
	Evolve to generation 16 by updating the submission catalog
	"""
	do_evolve(context, generation)
