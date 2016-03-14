#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 15

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.location.interfaces import ISublocations

from zope.location.location import locate

from persistent.list import PersistentList

from nti.app.assessment._question_map import ContentUnitAssessmentItems

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

def update_store(unit, container):
	store = ContentUnitAssessmentItems(unit)
	for item in container:
		interface.noLongerProvides(item, ISublocations)
		store[item.ntiid] = item
	store.createdTime = getattr(container, 'createdTime', 0)
	store.lastModified = getattr(container, 'lastModified', store.createdTime)

def update_unit_as_attribute(unit):
	try:
		container = unit._question_map_assessment_item_container
		if not isinstance(container, PersistentList):
			return False

		# XXX: delete attribute as persistent list
		delattr(unit, '_question_map_assessment_item_container')
		
		# rebuild store
		update_store(unit, container)
		del container[:]
		locate(container, None, None)

		return True
	except AttributeError:
		pass
	return False

def update_unit_as_annotation(unit):
	try:
		annotations = IAnnotations(unit)
		if not '_question_map_assessment_item_container' in annotations:
			return False
		container = annotations['_question_map_assessment_item_container']

		# XXX: delete annotation
		del annotations['_question_map_assessment_item_container']
		
		# rebuild store
		update_store(unit, container.values())
		container.clear(event=False)
		locate(container, None, None)

		return True
	except AttributeError:
		pass
	return False

def update_unit(unit):
	if not update_unit_as_attribute(unit):
		update_unit_as_annotation(unit)

def update_package(package):
	def _update(unit):
		for child in unit.children or ():
			_update(child)
		update_unit(unit)
	_update(package)

def update_library():
	library = component.queryUtility(IContentPackageLibrary)
	if library is not None:
		for package in library.contentPackages:
			update_package(package)

def do_evolve(context, generation):
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

		# Rub in all hosts
		run_job_in_all_host_sites(update_library)

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Finished app assessment evolve (%s)', generation)

def evolve(context):
	"""
	Evolve to generation 15 by updating the assesment item container
	"""
	do_evolve(context, generation)
