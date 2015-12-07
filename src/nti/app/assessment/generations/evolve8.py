#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 8

from zope import component

from zope.component.hooks import site, setHooks

from zope.intid import IIntIds

from zope.location.location import locate

from ..index import IX_COURSE
from ..index import CourseIntIDIndex
from ..index import install_assesment_catalog

from ..interfaces import IUsersCourseInquiryItem
from ..interfaces import IUsersCourseAssignmentHistoryItem

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

		total = 0
		assesment_catalog = install_assesment_catalog(ds_folder, intids)
		old_index = assesment_catalog[IX_COURSE]
		if not isinstance(old_index, CourseIntIDIndex):
			intids.unregister(old_index)
			del assesment_catalog[IX_COURSE]
			locate(old_index, None, None)

			new_index = CourseIntIDIndex(family=intids.family)
			intids.register(new_index)
			locate(new_index, assesment_catalog, IX_COURSE)
			assesment_catalog[IX_COURSE] = new_index

			for doc_id in old_index.ids():
				obj = intids.queryObject(doc_id)
				if 		IUsersCourseInquiryItem.providedBy(obj) \
					or	IUsersCourseAssignmentHistoryItem.providedBy(obj):
					total += 1
					new_index.index_doc(doc_id, obj)

			# clear old
			old_index.clear()

		logger.info('Assessment evolution %s done; %s items(s) indexed',
					generation, total)

def evolve(context):
	"""
	Evolve to generation 8 by replacing the course index in the assesment catalog
	"""
	do_evolve(context)
