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
import codecs
import argparse

from zope import component

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import set_site
from nti.dataserver.utils.base_script import create_context

from nti.ntiids.ntiids import find_object_with_ntiid

from .._common_reports import course_submission_report

def _create_report(course, usernames=(), assignment_id=None,
				   question_id=None, output=None):

	if output:
		output = codecs.open(output, "wb", "UTF-8")
	else:
		output = sys.stderr

	course_submission_report(context=course,
							 usernames=usernames,
							 question=question_id,
							 assignment=assignment_id,
							 stream=output)
	if output != sys.stderr:
		output.close()

def _process_args(args):
	set_site(args.site)

	course_id = args.course
	obj = find_object_with_ntiid(course_id)
	course_instance = ICourseInstance(obj, None)
	if course_instance is None:
		try:
			catalog = component.getUtility(ICourseCatalog)
			catalog_entry = catalog.getCatalogEntry(course_id)
			course_instance = ICourseInstance(catalog_entry, None)
		except KeyError:
			raise ValueError("Course not found")

	if course_instance is None:
		raise ValueError("Course not found")

	if args.assignment:
		assignment = component.queryUtility(IQAssignment, name=args.assignment)
		if assignment is None:
			raise ValueError("Assignment not found")

	if args.question:
		question = component.queryUtility(IQuestion, name=args.question)
		if question is None:
			raise ValueError("Question not found")

	usernames = {x.lower() for x in args.usernames or ()}
	_create_report(output=args.output,
				   usernames=usernames,
				   course=course_instance,
				   question_id=args.question,
				   assignment_id=args.assignment)

def main():
	arg_parser = argparse.ArgumentParser(description="Assignment submission report")
	arg_parser.add_argument('-c', '--course',
							 dest='course',
							 help="Course entry ntiid")
	arg_parser.add_argument('-a', '--assignment',
							 dest='assignment',
							 help="Assignment entry ntiid")
	arg_parser.add_argument('-q', '--question',
							 dest='question',
							 help="Question entry ntiid")
	arg_parser.add_argument('-o', '--output',
							dest='output',
							help="Output file name.")
	arg_parser.add_argument('-u', '--usernames',
							dest='usernames',
							nargs="+",
							help="The user names")
	arg_parser.add_argument('--site',
							dest='site',
							help="Application SITE.")

	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	if not args.course:
		raise IOError("Must specify a course/catalog entry NTIID")

	conf_packages = ('nti.appserver',)
	context = create_context(env_dir, with_library=False)

	run_with_dataserver(environment_dir=env_dir,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						function=lambda: _process_args(args))
	sys.exit(0)

if __name__ == '__main__':
	main()
