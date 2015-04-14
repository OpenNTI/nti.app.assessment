#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import csv
import sys
import argparse

from zope import component

from nti.contentlibrary.interfaces import IContentPackageLibrary
		
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.sharing import on_enroll_record_scope_membership

from nti.dataserver.users import User
from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import set_site
from nti.dataserver.utils.base_script import create_context

from .._assessment import move_user_assignment_from_course_to_course

def fix_enrollment_perms(verbose=True):
	cat = component.getUtility(ICourseCatalog)
	for cat_entry in cat.iterCatalogEntries():
		course = ICourseInstance(cat_entry)
		enrollments  = ICourseEnrollments(course)
		for record in enrollments.iter_enrollments():
			if record.Principal:
				if verbose:
					logger.info("Setting scopes for %s in %s", 
								record.Principal, cat_entry.ProviderUniqueID)
				on_enroll_record_scope_membership(record, None, course)

def move_user_assignments(input_file, dry_run=False, verbose=True):
	catalog = component.getUtility(ICourseCatalog)
	with open(input_file, 'rU') as f:
		rdr = csv.reader(f)
		for row in rdr:
			username = row[0]
			user = User.get_user(username)
			if user is None:
				if verbose:
					logger.warn('User %s not found', username)
				continue

			old_course_name = row[1]
			new_course_name = row[2]

			old_course = catalog.getCatalogEntry(old_course_name)
			old_course = ICourseInstance(old_course)
			
			new_course = catalog.getCatalogEntry(new_course_name)
			new_course = ICourseInstance(new_course)
			
			if verbose:
				logger.info("Moving assignment history for %s from %s to %s",
							username, old_course_name, new_course_name)
			
			if not dry_run:
				move_user_assignment_from_course_to_course(user, old_course, new_course,
														   verbose=verbose)
			
def _process_args(site, input_file, dry_run=False, verbose=True, with_library=True):
	set_site(site)

	if dry_run and not verbose:
		verbose = True
		
	if with_library and not dry_run:
		component.getUtility(IContentPackageLibrary).syncContentPackages()
		
	move_user_assignments(input_file, dry_run=dry_run, verbose=verbose)

def main():
	arg_parser = argparse.ArgumentParser(description="Enrollment fixer")
	arg_parser.add_argument('-v', '--verbose', help="Be Verbose", action='store_true',
							dest='verbose')
	arg_parser.add_argument('-d', '--dry', action='store_true',
							dest='dry_run',
							help="Dry run.")
	arg_parser.add_argument('-s', '--site',
							dest='site',
							default='janux.ou.edu',
							help="Application SITE.")
	arg_parser.add_argument('-i', '--input',
							dest='input',
							default='/tmp/move_assignments.csv',
							help="Input file.")
	
	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")
	
	if not args.site:
		raise IOError("Must specify a site name")
	
	site = args.site
	verbose = args.verbose
	dry_run = args.dry_run
	
	input_file = args.input
	if not os.path.exists(input_file):
		raise IOError("Move assignments file not found")
	
	context = create_context(env_dir)
	conf_packages = ('nti.appserver',)
	run_with_dataserver(environment_dir=env_dir,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						verbose=verbose,
						function=lambda: _process_args(	site, input_file, dry_run, verbose))
	sys.exit(0)

if __name__ == '__main__':
	main()
