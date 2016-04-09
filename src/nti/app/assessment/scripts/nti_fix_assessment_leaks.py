#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import sys
import argparse
from collections import defaultdict

from zope import component

from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.assessment._question_index import QuestionIndex

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ALL_EVALUATION_MIME_TYPES

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import create_context

from nti.intid.common import removeIntId

from nti.metadata import dataserver_metadata_catalog
				
from nti.site.hostpolicy import get_all_host_sites

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

def _master_data_collector():
	seen = set()
	registered = {}
	containers = defaultdict(list)
		
	def recur(unit):
		for child in unit.children or ():
			recur(child)
		container = IQAssessmentItemContainer(unit)
		for item in container.assessments():
			containers[item.ntiid].append(container)
	
	for site in get_all_host_sites():
		registry = site.getSiteManager()
		for ntiid, item in list(registry.getUtilitiesFor(IQEvaluation)):
			if ntiid not in registered:
				registered[ntiid] = (site, item)

		with current_site(site):
			for package in yield_sync_content_packages():
				if package.ntiid not in seen:
					seen.add(package.ntiid)
					recur(package)

	return registered, containers

def _get_data_item_counts(intids):
	count = defaultdict(list)
	catalog = dataserver_metadata_catalog()
	query = {
		'mimeType': {'any_of': ALL_EVALUATION_MIME_TYPES}
	}
	for uid in catalog.apply(query) or ():
		item = intids.queryObject(uid)
		if IQEvaluation.providedBy(item):
			count[item.ntiid].append(item)
	return count

def _process_args(verbose=True, with_library=True):
	library = component.getUtility(IContentPackageLibrary)
	library.syncContentPackages()
	
	intids = component.getUtility(IIntIds)
	count = _get_data_item_counts(intids)
	logger.info('%s item(s) counted', len(count))
	
	all_registered, all_containers = _master_data_collector()

	result = 0
	catalog = get_library_catalog()
	for ntiid, data in count.items():
		if len(data) <= 1:
			continue
		logger.warn("%s has %s duplicate(s)", ntiid, len(data) - 1)

		# find registry and registered objects
		context = data[0]  # pivot
		provided = iface_of_assessment(context)
		things = all_registered.get(ntiid)
		if not things:
			logger.warn("No registration found for %s", ntiid)	
			for item in data:
				iid = intids.queryId(item)
				if iid is not None:
					removeIntId(item)
			continue

		site, registered = things
		registry = site.getSiteManager()
		
		# if registered has been found.. check validity
		ruid = intids.queryId(registered)
		if ruid is None:
			logger.warn("Invalid registration for %s", ntiid)		
			unregisterUtility(registry, provided=provided, name=ntiid)
			# register a valid object
			registered = context
			ruid = intids.getId(context)
			registerUtility(registry, context, provided, name=ntiid)
			# update map
			all_registered[ntiid] = (site, registered)

		for item in data:
			doc_id = intids.getId(item)
			if doc_id != ruid:
				result += 1
				item.__parent__ = None
				catalog.unindex(doc_id)
				removeIntId(item)

		# canonicalize
		QuestionIndex.canonicalize_object(registered, registry)
		
	# check all registered items
	for ntiid, things in all_registered.items():
		_, registered = things
		containers = all_containers.get(ntiid)

		# fix lineage
		if registered.__parent__ is None and containers:	
			unit = find_interface(containers[0], IContentUnit, strict=False)
			if unit is not None:
				logger.warn("Fixing lineage for %s", ntiid)	
				registered.__parent__ = unit

		# make sure containers have registered object
		for container in containers or ():
			item = container.get(ntiid)
			if item is not registered:
				if intids.queryId(item) is not None:
					removeIntId(item)
				logger.warn("Adjusting container for %s", ntiid)
				container.pop(ntiid, None)
				container[ntiid] = registered

	logger.info('Done!!!, %s record(s) unregistered', result)

def main():
	arg_parser = argparse.ArgumentParser(description="Assessment leak fixer")
	arg_parser.add_argument('-v', '--verbose', help="Be Verbose", action='store_true',
							dest='verbose')

	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	verbose = args.verbose

	context = create_context(env_dir, with_library=True)
	conf_packages = ('nti.appserver',)
	run_with_dataserver(environment_dir=env_dir,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						verbose=verbose,
						function=lambda: _process_args(verbose))
	sys.exit(0)

if __name__ == '__main__':
	main()
