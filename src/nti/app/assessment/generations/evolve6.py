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

from zope.location.location import locate

from persistent.list import PersistentList

from nti.app.assessment._question_map import _AssessmentItemBucket

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

def update_unit(unit):
	try:
		container = unit._question_map_assessment_item_container
		if isinstance(container, PersistentList):
			delattr(unit, '_question_map_assessment_item_container') # remove
			bucket = unit._question_map_assessment_item_container = _AssessmentItemBucket()
			bucket.__parent__ = unit
			bucket.__name__ = container.__name__
			bucket.createdTime = container.createdTime
			bucket.lastModified = container.lastModified
			bucket.extend(container)
			del container[:] # clean
			locate(container, None, None)
	except AttributeError:
		pass

def update_package(package):
	def _update(unit):
		update_unit(unit)
		for child in unit.children or ():
			_update(child)
	_update(package)

def update_library():
	library = component.queryUtility(IContentPackageLibrary)
	if library is not None:
		logger.info('Migrating library (%s)', library)
		for package in library.contentPackages:
			update_package(package)

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

		run_job_in_all_host_sites(update_library)

	logger.info('Finished app assessment evolve (%s)', generation)

def evolve(context):
	"""
	Evolve to generation 6 by updating the assesment item container
	"""
	do_evolve(context)
