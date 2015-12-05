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

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contentlibrary.interfaces import IGlobalContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import create_context

from nti.site.hostpolicy import get_all_host_sites

def _process_pacakge(site, library, package, intids, catalog):

	results = defaultdict(int)
	results['reparented'] = results['replaced'] = results['removed'] = 0

	def _examine(unit):
		hierarchy_ntiids = set()
		hierarchy_ntiids.add(package.ntiid)
		containing_content_units = library.pathToNTIID(unit.ntiid)
		hierarchy_ntiids.update((x.ntiid for x in containing_content_units))

		items = IQAssessmentItemContainer(unit)
		for name, item in list(items.items()):  # mutating
			uid = intids.queryId(item)
			provided = iface_of_assessment(item)
			registered = component.queryUtility(provided, name=name)
			if uid is None:
				if registered is None:
					results['removed'] = results['removed'] + 1
					del items[name]
					continue
				elif id(registered) != id(item):
					results['replaced'] = results['replaced'] + 1
					items[name] = registered
					item = registered
				else:
					intids.register(item, event=True)  # gain and intid
					catalog.index(item,
							  	  container_ntiids=hierarchy_ntiids,
								  namespace=package.ntiid,
								  sites=(site.__name__,))
			elif registered is not None and id(registered) != id(item):
				results['replaced'] = results['replaced'] + 1
				items[name] = registered
				# unregister from intid
				intids.unregister(item, event=True)
				catalog.unindex(item)
				# replace
				item = registered

			if item.__parent__ is None:
				results['reparented'] = results['reparented'] + 1
				item.__parent__ = unit
				catalog.index(item,
							  container_ntiids=hierarchy_ntiids,
							  namespace=package.ntiid,
							  sites=(site.__name__,))

		for child in unit.children or ():
			_examine(child)

	_examine(package)
	logger.info("Pacakge %s removed=%s, replaced=%s, reparented=%s",
				package.ntiid, results['removed'], results['replaced'],
				results['reparented'])

def _process_args(verbose=True):
	library = component.getUtility(IContentPackageLibrary)
	library.syncContentPackages()

	seen = set()
	catalog = get_library_catalog()
	intids = component.getUtility(IIntIds)
	for site in get_all_host_sites():
		with current_site(site):
			library = component.queryUtility(IContentPackageLibrary)
			if library is not None:
				for pacakge in library.contentPackages:
					if 		not IGlobalContentPackage.providedBy(pacakge) \
						and pacakge.ntiid not in seen:
						_process_pacakge(site, library, pacakge, intids, catalog)
						seen.add(pacakge.ntiid)

def main():
	arg_parser = argparse.ArgumentParser(description="Unit container fixer")
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
