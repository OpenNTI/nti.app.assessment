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
from collections import OrderedDict

from zope import component

from zope.component.hooks import site as current_site

from zope.interface.adapter import _lookupAll as zopeLookupAll  # Private func

from zope.intid.interfaces import IIntIds

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ASSESSMENT_INTERFACES

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.indexed_data import get_library_catalog

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import create_context

from nti.intid.common import removeIntId

from nti.site.hostpolicy import get_all_host_sites

from nti.site.utils import unregisterUtility

def _assessment_containers():
	seen = set()
	containers = defaultdict(list)

	def recur(unit):
		for child in unit.children or ():
			recur(child)
		container = IQAssessmentItemContainer(unit)
		for item in container.assessments():
			containers[item.ntiid].append(container)

	for site in get_all_host_sites():
		with current_site(site):
			for package in yield_sync_content_packages():
				if package.ntiid not in seen:
					seen.add(package.ntiid)
					recur(package)

	return containers

def _lookup_all_assessments(site_registry):
	result = {}
	required = ()
	order = len(required)
	for registry in site_registry.utilities.ro:  # must keep order
		byorder = registry._adapters
		if order >= len(byorder):
			continue
		components = byorder[order]
		extendors = ASSESSMENT_INTERFACES
		zopeLookupAll(components, required, extendors, result, 0, order)
		break  # break on first
	return result

def _remove_invalid_assessment(site, provided, ntiid, containers):
	# remove from current site registry
	registry = site.getSiteManager()
	unregisterUtility(registry, provided=provided, name=ntiid)
	# check containers
	with current_site(site):
		registered = component.queryUtility(provided, name=ntiid)
		for container in containers.get(ntiid) or ():
			if registered is None:
				container.pop(ntiid, None)
			else:
				containers[ntiid] = registered

def remove_site_invalid_assessments(current, containers, intids=None,
									catalog=None, seen=None):
	removed = set()
	site_name = current.__name__
	registry = current.getSiteManager()

	# get defaults
	seen = set() if seen is None else seen
	catalog = get_library_catalog() if catalog is None else catalog
	intids = component.getUtility(IIntIds) if intids is None else intids

	# get all assets in site/no hierarchy
	site_components = _lookup_all_assessments(registry)
	logger.info("%s assessment(s) found in %s", len(site_components), site_name)

	for ntiid, item in site_components.items():
		provided = iface_of_assessment(item)
		doc_id = intids.queryId(item)

		# registration for a removed assessment
		if doc_id is None:
			logger.warn("Removing invalid registration (%s,%s) from site %s",
						provided.__name__, ntiid, site_name)
			removed.add(ntiid)
			_remove_invalid_assessment(current, provided, ntiid, containers)
			continue

		# registration not in base site
		if ntiid in seen:
			removed.add(ntiid)
			logger.warn("Unregistering (%s,%s) from site %s",
						provided.__name__, ntiid, site_name)
			removeIntId(item)
			_remove_invalid_assessment(current, provided, ntiid, containers)
			continue

		if item.__parent__ is None:
			for container in containers.get(ntiid) or ():
				item.__parent__ = container  # pick first
				break

		seen.add(ntiid)
	return removed

def remove_all_invalid_assessment(containers):
	seen = set()
	result = OrderedDict()
	catalog = get_library_catalog()
	intids = component.getUtility(IIntIds)
	for current in get_all_host_sites():
		removed = remove_site_invalid_assessments(current,
												  seen=seen,
												  intids=intids,
												  catalog=catalog,
												  containers=containers)
		result[current.__name__] = sorted(removed)
	return result

def _process_args(args):
	library = component.getUtility(IContentPackageLibrary)
	library.syncContentPackages()
	logger.info("Loading assesments containers")
	containers = _assessment_containers()
	remove_all_invalid_assessment(containers=containers)

def main():
	arg_parser = argparse.ArgumentParser(description="Remove invalid assessments")
	arg_parser.add_argument('-v', '--verbose', help="Be Verbose", action='store_true',
							dest='verbose')

	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	conf_packages = ('nti.appserver',)
	context = create_context(env_dir, with_library=True)

	run_with_dataserver(environment_dir=env_dir,
						verbose=args.verbose,
						context=context,
						minimal_ds=True,
						xmlconfig_packages=conf_packages,
						function=lambda: _process_args(args))
	sys.exit(0)

if __name__ == '__main__':
	main()
