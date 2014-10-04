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
import json
import codecs
import argparse

from zope import component
from zope.component import hooks

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver.utils import run_with_dataserver

from nti.externalization.externalization import to_external_object

from nti.ntiids.ntiids import TYPE_OID
from nti.ntiids.ntiids import is_ntiid_of_type
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.site import get_site_for_site_names

from .base import create_context

def _replace(username):
	try:
		from nti.app.products.gradebook.interfaces import IUsernameSortSubstitutionPolicy
		policy = component.queryUtility(IUsernameSortSubstitutionPolicy)
		if policy is not None:
			return policy.replace(username) or username
	except ImportError:
		pass
	return username
	
def _create_report(course, assignment_id=None, question_id=None, output=None,
				   separator='\t'):
	
	if output:
		output = codecs.open(output, "wb", "UTF-8")
	else:
		output = sys.stderr
		
	header = ['username', 'assignment', 'question', 'part', 'submission']
	output.write(separator.join(header))
	output.write("\n")

	course_enrollments = ICourseEnrollments( course )
	for record in course_enrollments.iter_enrollments():
		principal = record.Principal
		username = principal.username
		history = component.getMultiAdapter( (course, principal),
											  IUsersCourseAssignmentHistory )
		for key, item in history.items():
			# filter assignment 
			if assignment_id and assignment_id != key:
				continue
			submission = item.Submission
			for qs_part in submission.parts:
				# all question submissions
				for question in qs_part.questions:
					# filter question 
					if question_id and question.questionId != question_id:
						continue
					
					qid = question.questionId
					for idx, sub_part in enumerate(question.parts):
						ext = json.dumps(to_external_object(sub_part))
						row_data = [_replace(username), key, qid, str(idx), ext]
						output.write(separator.join(row_data))
						output.write("\n")

	if output != sys.stderr:
		output.close()
		
def _process_args(args):
	site = args.site
	if site:
		cur_site = hooks.getSite()
		new_site = get_site_for_site_names( (site,), site=cur_site )
		if new_site is cur_site:
			raise ValueError("Unknown site name", site)
		hooks.setSite(new_site)

	course_id = args.course
	if not is_ntiid_of_type(course_id, TYPE_OID):
		try:
			catalog = component.getUtility(ICourseCatalog)
			catalog_entry = catalog.getCatalogEntry(course_id)
			course_instance = ICourseInstance(catalog_entry)
		except KeyError:
			raise ValueError("Course not found")
	else:
		obj = find_object_with_ntiid(course_id)
		course_instance = ICourseInstance(obj, None)
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

	_create_report(course_instance, 
				   args.assignment,
				   args.question, 
				   args.output)
	
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
	arg_parser.add_argument('--site',
							dest='site',
							help="Application SITE.")
	
	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	if not args.course:
		raise IOError("Must specify a course NTIID")
	
	context = create_context(env_dir, with_library=False)
	conf_packages = ('nti.appserver',)

	run_with_dataserver(environment_dir=env_dir,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						function=lambda: _process_args(args))
	sys.exit(0)

if __name__ == '__main__':
	main()
