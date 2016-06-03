#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 23

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.contentlibrary.utils import yield_content_packages

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.proxy import removeAllProxies

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.metadata import get_uid
from nti.metadata.interfaces import IMetadataQueue

from nti.site.hostpolicy import get_all_host_sites

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

def _process_items(registry, queue, intids, seen):
	
	def _recur(unit, lastMod):
		container = IQAssessmentItemContainer(unit)
		for item in container.assessments():
			if 		(IQuestion.providedBy(item) or IQuestionSet.providedBy(item)) \
				and not IQEditableEvaluation.providedBy(item):
				item = registry.getUtility(IQEvaluation, item.ntiid)
				if item is not None:
					item = removeAllProxies(item)
					item.lastModified = item.createdTime = lastMod
					uid = get_uid(item, intids)
					if uid is not None:
						try:
							queue.add(uid)
						except TypeError:
							pass

		for child in unit.children or ():
			_recur(child, lastMod)
	
	for pacakge in yield_content_packages():
		if pacakge.ntiid in seen:
			continue
		seen.add(pacakge.ntiid)
		main_container = IQAssessmentItemContainer(pacakge)
		_recur(pacakge, main_container.lastModified or 0)

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']
	lsm = ds_folder.getSiteManager()
	intids = lsm.getUtility(IIntIds)
	queue = lsm.getUtility(IMetadataQueue)

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	with current_site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		# Load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		seen = set()
		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()
				_process_items(registry, queue, intids, seen)

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 23 by setting the lastMod and createdTime to question 
	and question set objects
	"""
	do_evolve(context)
