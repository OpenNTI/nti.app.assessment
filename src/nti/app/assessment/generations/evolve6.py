#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 6

from zope import component
from zope import interface

from zope.component.hooks import site, setHooks

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import run_job_in_all_host_sites

from nti.contentlibrary.interfaces import IContentPackageLibrary

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

def _drop_annotation(unit):
	annote = IQAssessmentItemContainer(unit, None)
	if hasattr(unit, '_question_map_assessment_item_container'):
		delattr(unit, '_question_map_assessment_item_container')
	return annote

def index_library():
	library = component.queryUtility(IContentPackageLibrary)
	if library is not None:
		logger.info('Migrating library (%s)', library)
		for package in library.contentPackages:
			_drop_annotation(package)

def do_evolve(context):
	setHooks()
	conn = context.connection
	root = conn.root()
	ds_folder = root['nti.dataserver']

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	with site(ds_folder):
		assert	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		# Load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		# Iterate through packages, dropping annotations
		index_library()
		run_job_in_all_host_sites(index_library)

	logger.info('Finished app assessment evolve (%s)', generation)

def evolve(context):
	"""
	Evolve to generation 5 dropping old assessment annotations.
	"""
	do_evolve(context)
