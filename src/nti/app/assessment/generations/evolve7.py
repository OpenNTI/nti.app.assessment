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

import functools

import zope.intid

from zope import component
from zope import interface

from zope.component.hooks import site, setHooks

from zope.catalog.interfaces import ICatalog

from nti.assessment.survey import QPollSubmission
from nti.assessment.survey import QSurveySubmission

from nti.app.products.courseware.interfaces import ICourseInstanceActivity

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver
from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.site.hostpolicy import run_job_in_all_host_sites

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

removed_count = 0

def _remove_from_course_activity( catalog, intids ):
	global removed_count
	mime_types = (QPollSubmission.mime_type, QSurveySubmission.mime_type)
	item_intids = catalog['mimeType'].apply({'any_of': mime_types})
	results = ResultSet(item_intids, intids, True)
	for _, submission in results.iter_pairs():
		course = find_interface(submission, ICourseInstance)
		activity = ICourseInstanceActivity(course)
		activity.remove(submission)
		removed_count += 1

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

	global removed_count

	with site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		catalog = lsm.getUtility(ICatalog, METADATA_CATALOG_NAME)

		run_job_in_all_host_sites( functools.partial( _remove_from_course_activity, catalog, intids ) )

		logger.info('Assessment evolution %s done (removed=%s)', generation, removed_count)

def evolve(context):
	"""
	Evolve to generation 7 by removing inquiries from course activity.
	"""
	do_evolve(context)
