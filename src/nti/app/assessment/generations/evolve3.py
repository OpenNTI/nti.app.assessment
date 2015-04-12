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
from zope.catalog.interfaces import ICatalog

from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.zope_catalog.catalog import ResultSet

from ..index import install_assesment_catalog

def do_evolve(context, generation=generation):
	logger.info("assesment evolution %s started", generation);
	
	conn = context.connection
	dataserver_folder = conn.root()['nti.dataserver']
	lsm = dataserver_folder.getSiteManager()
	intids = lsm.getUtility(zope.intid.IIntIds)
	
	# install assesment catalog
	assesment_catalog = install_assesment_catalog(dataserver_folder, intids)
	
	# index all course history items
	total = 0
	metadata_catalog = component.getUtility(ICatalog, METADATA_CATALOG_NAME)
	ITEM_MT = 'application/vnd.nextthought.assessment.userscourseassignmenthistoryitem'
	item_intids = metadata_catalog['mimeType'].apply({'any_of': (ITEM_MT,)})
	results = ResultSet(item_intids, intids, True)
	for uid, obj in results.iter_pairs():
		try:
			assesment_catalog.force_index_doc(uid, obj)
			total += 1
		except Exception:
			logger.warn("Cannot index object with id %s", uid)
	
	logger.info('assesment evolution %s done; %s items(s) indexed',
				generation, total)

def evolve(context):
	"""
	Evolve to generation 3 by installing an assesment index
	"""
	do_evolve(context)
