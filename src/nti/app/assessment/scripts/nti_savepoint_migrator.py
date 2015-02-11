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

from nti.assessment.interfaces import IQAssignment

from nti.dataserver.users import User
from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import set_site
from nti.dataserver.utils.base_script import create_context

from .._utils import find_course_for_assignment

from .._submission import transfer_upload_ownership

from ..interfaces import IUsersCourseAssignmentHistory
from ..interfaces import IUsersCourseAssignmentSavepoint

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
	set_site(args.site)

	username = args.username
	creator = User.get_entity(username or u'')
	if not creator:
		raise ValueError("Invalid user")
	
	assignmentId = args.assignment
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
		raise IOError("Must specify a username")
	
	if not args.assignment:
		raise IOError("Must specify an assignment")
	
	context = create_context(env_dir)
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
