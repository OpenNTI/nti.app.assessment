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

from zope.intid.interfaces import IIntIds

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import create_context

from nti.site.hostpolicy import get_all_host_sites

def _get_registered_component(provided, name=None):
	for site in get_all_host_sites():
		try:
			registry = site.getSiteManager()
			registered = registry.queryUtility(provided, name=name)
			if registered is not None:
				return registered
		except KeyError:
			pass
	return None

def _get_item_counts():
	count = defaultdict(list)
	intids = component.getUtility(IIntIds)
	for _, item in intids.items():
		if IQAssessment.providedBy(item):
			count[item.ntiid].append(item)
	return count

def _process_args(verbose=True, with_library=True):
	logger.info('Getting item counts ...')
	count = _get_item_counts()
	logger.info('%s item(s) counted', len(count))

	result = 0
	intids = component.getUtility(IIntIds)
	for ntiid, data in count.items():
		if len(data) <= 1:
			continue

		context = data[0]  # pivot
		provided = iface_of_assessment(context)
		registered = _get_registered_component(provided, ntiid)
		if registered is not None:
			ruid = intids.queryId(registered)
			if ruid is None:
				ruid = intids.register(registered, event=True)
			container = IQAssessmentItemContainer(registered.__parent__, None)
			if container is not None:
				container.append(registered)  # replace
		else:
			ruid = None

		for item in data:
			if intids.getId(item) != ruid:
				result += 1
				item.__parent__ = None
				intids.unregister(item, event=True)

	logger.info('Done!!!, %s record(s) unregistered', result)

def main():
	arg_parser = argparse.ArgumentParser(description="Enrollment fixer")
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
