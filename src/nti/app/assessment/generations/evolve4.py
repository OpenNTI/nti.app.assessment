#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 4

import functools

from zope import component
from zope import interface

from zope.component.hooks import site, setHooks

from zope.intid.interfaces import IIntIds

from nti.app.assessment._question_map import QuestionMap

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

def _index_assessment(assessment_item, unit, hierarchy_ntiids):
	question_map = QuestionMap()
	return question_map._index_object(assessment_item, unit, hierarchy_ntiids)

def _index_assessment_items(unit, intids):
	"""
	For our unit, index the assessment items, registering as needed.
	"""
	def recur(unit, hierarchy_ntiids):
		indexed_count = 0
		try:
			qs = IQAssessmentItemContainer(unit).assessments()
		except TypeError:
			qs = ()

		hierarchy_ntiids = set(hierarchy_ntiids)
		hierarchy_ntiids.add(unit.ntiid)
		if qs:
			for assessment_item in qs or ():
				if not intids.queryId(assessment_item):
					intids.register(assessment_item, event=False)
				did_index = _index_assessment(assessment_item, unit, hierarchy_ntiids)
				if did_index:
					indexed_count += 1

		for child in unit.children:
			indexed_count += recur(child, hierarchy_ntiids)
		return indexed_count

	hierarchy_ntiids = set()
	indexed_count = recur(unit, hierarchy_ntiids)
	return indexed_count

def index_library(intids):
	library = component.queryUtility(IContentPackageLibrary)
	if library is not None:
		logger.info('Migrating library (%s)', library)
		for package in library.contentPackages:
			# Migrate/store the global assessments too
			indexed_count = _index_assessment_items(package, intids)
			logger.info('Indexed (%s) (count=%s)', package, indexed_count)

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
		lsm = ds_folder.getSiteManager()
		intids = lsm.getUtility(IIntIds)

		# Load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		# Iterate through packages, dropping annotation
		# and indexing.
		index_library(intids)
		run_job_in_all_host_sites(functools.partial(index_library, intids))

	logger.info('Finished app assessment evolve (%s)', generation)

def evolve(context):
	"""
	Evolve to generation 4 by moving assessment catalog to library catalog.
	"""
	do_evolve(context)
