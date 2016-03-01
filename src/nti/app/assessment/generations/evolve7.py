#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 7.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 7

import zope.intid

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.catalog.interfaces import ICatalog

from nti.assessment.survey import QPollSubmission
from nti.assessment.survey import QSurveySubmission

from nti.app.products.courseware.interfaces import ICourseInstanceActivity

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver
from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.traversal.traversal import find_interface

from nti.zope_catalog.catalog import ResultSet

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

def _remove_from_course_activity(catalog, intids):
	removed_count = 0
	mime_types = (QPollSubmission.mime_type, QSurveySubmission.mime_type)
	item_intids = catalog['mimeType'].apply({'any_of': mime_types})
	for submission in ResultSet(item_intids, intids, True):
		course = find_interface(submission, ICourseInstance, strict=False)
		if course is not None:
			activity = ICourseInstanceActivity(course)
			activity.remove(submission)
			removed_count += 1
	return removed_count

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

	with current_site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		catalog = lsm.getUtility(ICatalog, METADATA_CATALOG_NAME)
		removed_count = _remove_from_course_activity(catalog, intids)

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done (removed=%s)', generation, removed_count)

def evolve(context):
	"""
	Evolve to generation 7 by removing inquiries from course activity.
	"""
	do_evolve(context)
