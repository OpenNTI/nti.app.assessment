#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.monkey import relstorage_patch_all_except_gevent_on_import
relstorage_patch_all_except_gevent_on_import.patch()

import os
import csv
import sys
import argparse

from zope import component
from zope.component import hooks
from zope.container.contained import Contained
from zope.configuration import xmlconfig, config
from zope.dottedname import resolve as dottedname

import zope.browserpage

from z3c.autoinclude.zcml import includePluginsDirective

from nti.app.assessment.adapters import _history_for_user_in_course

from nti.contentlibrary.interfaces import IContentPackageLibrary
		
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.sharing import on_enroll_record_scope_membership

from nti.dataserver.users import User
from nti.dataserver.utils import run_with_dataserver

from nti.site.site import get_site_for_site_names

class PluginPoint(Contained):

	def __init__(self, name):
		self.__name__ = name

PP_APP = PluginPoint('nti.app')
PP_APP_SITES = PluginPoint('nti.app.sites')
PP_APP_PRODUCTS = PluginPoint('nti.app.products')

def _create_context(env_dir=None):
	etc = os.getenv('DATASERVER_ETC_DIR') or os.path.join(env_dir, 'etc')
	etc = os.path.expanduser(etc)

	context = config.ConfigurationMachine()
	xmlconfig.registerCommonDirectives(context)

	slugs = os.path.join(etc, 'package-includes')
	if os.path.exists(slugs) and os.path.isdir(slugs):
		package = dottedname.resolve('nti.dataserver')
		context = xmlconfig.file('configure.zcml', package=package, context=context)
		xmlconfig.include(context, files=os.path.join(slugs, '*.zcml'),
						  package='nti.appserver')

	library_zcml = os.path.join(etc, 'library.zcml')
	if not os.path.exists(library_zcml):
		raise Exception("Could not locate library zcml file %s", library_zcml)
	xmlconfig.include(context, file=library_zcml, package='nti.appserver')
		
	# Include zope.browserpage.meta.zcm for tales:expressiontype
	# before including the products
	xmlconfig.include(context, file="meta.zcml", package=zope.browserpage)

	# include plugins
	includePluginsDirective(context, PP_APP)
	includePluginsDirective(context, PP_APP_SITES)
	includePluginsDirective(context, PP_APP_PRODUCTS)
	
	return context

def fix_enrollment_perms(verbose=True):
	cat = component.getUtility(ICourseCatalog)
	for cat_entry in cat.iterCatalogEntries():
		course = ICourseInstance(cat_entry)
		enrollments  = ICourseEnrollments(course)
		for record in enrollments.iter_enrollments():
			if record.Principal:
				if verbose:
					print("Setting scopes for", record.Principal, "in", 
						  cat_entry.ProviderUniqueID)
				on_enroll_record_scope_membership(record, None, course)

def move_user_assignment_from_course_to_course(user, old_course, new_course, verbose=True):
	old_history = _history_for_user_in_course(old_course, user)
	new_history = _history_for_user_in_course(new_course, user)
	for k in list(old_history):
		item = old_history[k]
		## JAM: do a full delete/re-add so that ObjectAdded event gets fired, 
		## because that's where auto-grading takes place
		del old_history[k]
		assert item.__name__ is None
		assert item.__parent__ is None
		if k in new_history:
			if verbose:
				print("Skipped moving", k, "for", user, "from", old_course.__name__, 
					  'to', new_course.__name__)
			continue

		new_history[k] = item
		if verbose:
			print("Moved", k, "for", user, "from", old_course.__name__, 
				  'to', new_course.__name__)

def move_user_assignments(input_file, dry_run=False, verbose=True):
	catalog = component.getUtility(ICourseCatalog)
	with open(input_file, 'rU') as f:
		rdr = csv.reader(f)

		for row in rdr:
			username = row[0]
			user = User.get_user(username)
			if user is None:
				if verbose:
					print('\t', username, 'not found')
				continue

			old_course_name = row[1]
			new_course_name = row[2]

			old_course = catalog.getCatalogEntry(old_course_name)
			old_course = ICourseInstance(old_course)
			new_course = catalog.getCatalogEntry(new_course_name)
			new_course = ICourseInstance(new_course)
			if verbose:
				print("\tMoving assignment history for", username, "from",
					  old_course_name, "to", new_course_name)
			if not dry_run:
				move_user_assignment_from_course_to_course(user, old_course, new_course)
			
def _process_args(site, input_file, dry_run=False, verbose=True,
				  with_library=True):
	
	cur_site = hooks.getSite()
	new_site = get_site_for_site_names((site,), site=cur_site )
	if new_site is cur_site:
		raise ValueError("Unknown site name", site)
	hooks.setSite(new_site)

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
	
	context = _create_context(env_dir)
	conf_packages = ('nti.appserver',)
	run_with_dataserver(environment_dir=env_dir,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						verbose=verbose,
						function=lambda: _process_args(	site, input_file,
														dry_run, verbose))
	sys.exit(0)

if __name__ == '__main__':
	main()
