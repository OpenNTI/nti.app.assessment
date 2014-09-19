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
import sys
import argparse
from urllib import unquote

import zope.browserpage

from zope import component
from zope.component import hooks
from zope.container.contained import Contained
from zope.configuration import xmlconfig, config
from zope.dottedname import resolve as dottedname

from z3c.autoinclude.zcml import includePluginsDirective

from nti.assessment.interfaces import IQAssignment

from nti.dataserver.users import User
from nti.dataserver.utils import run_with_dataserver

from nti.site.site import get_site_for_site_names

from nti.app.assessment._utils import transfer_upload_ownership
from nti.app.assessment._utils import find_course_for_assignment

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint

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
	
def _migrator(creator, assignmentId, delete=False):
	assignment = component.getUtility(IQAssignment, assignmentId)
	course = find_course_for_assignment(assignment, creator)
	if course is None:
		logger.error("User not enrolled in course (invalid  assignment/creator pair?)")
		return 

	assignment_history = component.getMultiAdapter( (course, creator),
													IUsersCourseAssignmentHistory )
		
	assignment_savepoint = component.getMultiAdapter((course, creator),
													 IUsersCourseAssignmentSavepoint )
	
	if assignmentId not in assignment_savepoint:
		logger.warn("Assignment not found in save point")
		return

	if assignmentId not in assignment_history:
		logger.warn("Assignment not found in history")
		return
		
	# get submission from assignment history
	submission = assignment_history[assignmentId].Submission
	# get submission from save point
	savepoint = assignment_savepoint[assignmentId].Submission
	# transfer files
	transfer_upload_ownership(submission, savepoint)
	# delete save point
	if delete:
		del assignment_savepoint[assignmentId]
		
def _process_args(args):
	site = args.site
	if site:
		cur_site = hooks.getSite()
		new_site = get_site_for_site_names( (site,), site=cur_site )
		if new_site is cur_site:
			raise ValueError("Unknown site name", site)
		hooks.setSite(new_site)

	username = args.username
	creator = User.get_entity(username or u'')
	if not creator:
		raise ValueError("Invalid user")
	
	assignmentId = unquote(args.assignment)
	assignment = component.queryUtility(IQAssignment, name=assignmentId)
	if assignment is None:
		raise ValueError("Invalid Assignment")

	_migrator(creator,  assignmentId, args.delete)
	
def main():
	arg_parser = argparse.ArgumentParser(description="Savepoint migrator")
	arg_parser.add_argument('-v', '--verbose', help="Be Verbose", action='store_true',
							dest='verbose')
	arg_parser.add_argument('-u', '--username', dest='username',
							 help="User name")
	arg_parser.add_argument('-a', '--assignment', dest='assignment',
							 help="Assignment entry ntiid")
	arg_parser.add_argument('-d', '--delete', help="Delete savepoint", action='store_true',
							dest='delete')
	arg_parser.add_argument('--site',
							dest='site',
							help="Application SITE.")
	
	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	if not args.username:
		raise ValueError("Must specify a username")
	
	if not args.assignment:
		raise ValueError("Must specify an assignment")
	
	context = _create_context(env_dir)
	conf_packages = ('nti.appserver',)
	run_with_dataserver(environment_dir=env_dir,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						verbose=args.verbose,
						function=lambda: _process_args(args))
	sys.exit(0)

if __name__ == '__main__':
	main()
