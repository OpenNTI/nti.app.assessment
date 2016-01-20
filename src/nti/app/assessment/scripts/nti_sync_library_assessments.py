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

from zope import component

from nti.app.assessment._question_map import update_assessment_items_when_modified

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import set_site
from nti.dataserver.utils.base_script import create_context

def _sync_content_assessment(pacakge):
	update_assessment_items_when_modified(pacakge)

def _sync_content_packages(args):
	for package in yield_sync_content_packages(args.ntiids):
		_sync_content_assessment(package)

def _process_args(args):
	library = component.getUtility(IContentPackageLibrary)
	library.syncContentPackages()
	set_site(args.site)

	if not args.list:
		_sync_content_packages(args)
	else:
		print()
		for package in yield_sync_content_packages():
			print("===>", package.ntiid)
		print()

def main():
	arg_parser = argparse.ArgumentParser(description="Package assessment synchronizer")
	arg_parser.add_argument('-v', '--verbose', help="Be Verbose", action='store_true',
							dest='verbose')

	arg_parser.add_argument('-s', '--site',
							dest='site',
							help="Application SITE.")

	site_group = arg_parser.add_mutually_exclusive_group()
	site_group.add_argument('-n', '--ntiids',
							 dest='ntiids',
							 nargs="+",
							 default=(),
							 help="The Package NTIIDs")

	site_group.add_argument('--all',
							 dest='all',
							 action='store_true',
							 help="All packages")

	site_group.add_argument('--list',
							 dest='list',
							 action='store_true',
							 help="List sync packages")

	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	if not args.site:
		raise ValueError("Application site not specified")

	conf_packages = ('nti.appserver',)
	context = create_context(env_dir, with_library=True)

	run_with_dataserver(environment_dir=env_dir,
						verbose=args.verbose,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						function=lambda: _process_args(args))
	sys.exit(0)

if __name__ == '__main__':
	main()
