#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Extraction and merging of assignment policy files.

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import sys
import os.path
import argparse

import simplejson

from zope.component import hooks
from zope.configuration import xmlconfig
from zope.interface.registry import Components

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQTimedAssignment

from nti.contentlibrary.filesystem import FilesystemKey
from nti.contentlibrary.filesystem import FilesystemBucket

from nti.externalization.externalization import to_external_object

from .._question_map import QuestionMap
from .._question_map import _load_question_map_json

def _load_assignments(json_string, json_key):

	index = _load_question_map_json(json_string)

	question_map = QuestionMap()

	class FakeContentPackage(object):

		def __init__(self, bucket):
			self.bucket = bucket

		def make_sibling_key(self, name):
			result = type(json_key)(bucket=self.bucket, name=name)
			return result

	assignment_registry = Components()
	question_map._from_root_index( index,
								   FakeContentPackage(json_key.__parent__),
								   registry=assignment_registry)
	return assignment_registry

def _asg_registry_to_course_data(registry):

	data = {}
	for assignment in registry.getAllUtilitiesRegisteredFor(IQAssignment):
		name = assignment.ntiid
		asg_data = data[name] = {}
		# title is for human readability; capitalized to sort to beginning
		asg_data['Title'] = assignment.title

		# the actual dates
		asg_data['available_for_submission_ending'] = \
				to_external_object(assignment.available_for_submission_ending)
		asg_data['available_for_submission_beginning'] = \
				to_external_object(assignment.available_for_submission_beginning)

		# max time allowed
		if IQTimedAssignment.providedBy(assignment):
			asg_data['maximum_time_allowed'] = assignment.maximum_time_allowed
		
		# Point specification
		point_data = asg_data['auto_grade'] = {}

		# Default total points is simply the sum of question/parts
		total_points = 0

		for part in assignment.parts:
			qset = part.question_set
			for question in qset.questions:
				total_points += len(question.parts)

		point_data['total_points'] = total_points

	return data

def _merge_disk(automatic_values, merge_values):
	for k in automatic_values:
		if k not in merge_values:
			continue

		manual_value = merge_values[k]
		automatic_value = automatic_values[k]

		# Some things we want to preserve, some we
		# want to force. For example, the title may change,
		# we want the new value.
		# But the dates should be preserved,
		# as should the auto_grade, exclusion, and nuclear_reset info
		# This whole process could be handled declaratively, see
		# how gunicorn does its config or plastex its for examples
		for d in ('available_for_submission_beginning',
				  'available_for_submission_ending',
				  'auto_grade',
				  'excluded',
				  'maximum_time_allowed',
				  'student_nuclear_reset_capable'):
			if d in manual_value:
				automatic_value[d] = manual_value[d]

	# TODO: What about old things that simply aren't present in the
	# automatic extract anymore? For now, we preserve them, but we may
	# want to drop them or move them to a separate key?
	for k in merge_values:
		if k in automatic_values:
			continue
		automatic_values[k] = merge_values[k]

def main_extract_assignments():
	"""
	A tool designed to ease the process for extracting just
	assignment data for overrides in courses.
	"""

	arg_parser = argparse.ArgumentParser(description="Extract assignment data")
	arg_parser.add_argument('assessment_index_json', type=file,
							help="Path to an assessment_index.json file")
	arg_parser.add_argument('--force-total-points', type=int,
							dest='force_total_points',
							help="Force all assignments to have this total point value")
	arg_parser.add_argument('--merge-with', type=file,
							help="Path to a file previously output by this command, and possibly edited."
							" New values will be added, but existing changes will be preserved.")

	args = arg_parser.parse_args()
	json_string = args.assessment_index_json.read()

	json_key = FilesystemKey()
	json_key.absolute_path = args.assessment_index_json.name
	dir_name, f_name = os.path.split(json_key.absolute_path)
	json_key.__name__ = f_name
	json_bucket = json_key.__parent__ = FilesystemBucket()
	json_bucket.absolute_path = dir_name

	# Now that we got this far, go ahead and configure
	hooks.setHooks()
	import nti.app.assessment
	xmlconfig.file('configure.zcml', package=nti.app.assessment)

	registry = _load_assignments(json_string, json_key)

	ext_value = _asg_registry_to_course_data(registry)

	if args.force_total_points:
		for asg in ext_value.values():
			asg['auto_grade']['total_points'] = args.force_total_points

	if args.merge_with:
		merge_json = simplejson.loads(args.merge_with.read())
		_merge_disk(ext_value, merge_json)

	simplejson.dump(ext_value,
					sys.stdout,
					indent='    ',
					separators=(', ', ': '),
					sort_keys=True)
	# trailing newline
	print('', file=sys.stdout)

main = main_extract_assignments # alias
