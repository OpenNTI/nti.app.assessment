#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""


.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

#disable: accessing protected members, too many methods
#pylint: disable=W0212,R0904

import unittest
from hamcrest import assert_that
from hamcrest import is_
from hamcrest import has_key
from hamcrest import has_entry

from nti.testing import base
from nti.testing import matchers

from . import AssessmentLayerTest
import simplejson as json

class TestAssignmentPolicyExtractor(AssessmentLayerTest):

	def test_extract_and_merge(self):
		asg_id = 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.asg.assignment'
		question = {'Class': 'Question',
					'MimeType': 'application/vnd.nextthought.naquestion',
					'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion',
					'content': '<a name="testquestion"></a> Arbitrary content goes here.',
					'parts': [{'Class': 'FilePart',
							   'MimeType': 'application/vnd.nextthought.assessment.filepart',
							   'allowed_extensions': [],
							   'allowed_mime_types': ['application/pdf'],
							   'content': 'Arbitrary content goes here.',
							   'explanation': u'',
							   'hints': [],
							   'max_file_size': None,
							   'solutions': []}]}


		the_map = {'Items':
		 {'tag:nextthought.com,2011-10:testing-HTML-temp.0':
		  {'AssessmentItems': {},
		   'Items': {'tag:nextthought.com,2011-10:testing-HTML-temp.chapter_one':
					 {'AssessmentItems': {},
					  'Items': {'tag:nextthought.com,2011-10:testing-HTML-temp.section_one':
								{'AssessmentItems': {asg_id:
													 {'Class': 'Assignment',
													  'MimeType': 'application/vnd.nextthought.assessment.assignment',
													  'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.asg.assignment',
													  'available_for_submission_beginning': '2014-01-13T00:00:00',
													  'available_for_submission_ending': None,
													  'content': 'Assignment content.',
													  'parts': [{'Class': 'AssignmentPart',
																 'MimeType': 'application/vnd.nextthought.assessment.assignmentpart',
																 'auto_grade': True,
																 'content': 'Some content.',
																 'question_set': {'Class': 'QuestionSet',
																				  'MimeType': 'application/vnd.nextthought.naquestionset',
																				  'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.set',
																				  'questions': [question]},
																 'title': 'Part Title'}],
													  'title': 'Main Title'},
													 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.set': {'Class': 'QuestionSet',
																												  'MimeType': 'application/vnd.nextthought.naquestionset',
																												  'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.set',
																												  'questions': [question]},
													 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion': question},
								 'NTIID': 'tag:nextthought.com,2011-10:testing-HTML-temp.section_one',
								 'filename': 'tag_nextthought_com_2011-10_testing-HTML-temp_section_one.html',
								 'href': 'tag_nextthought_com_2011-10_testing-HTML-temp_section_one.html'}},
					  'NTIID': 'tag:nextthought.com,2011-10:testing-HTML-temp.chapter_one',
					  'filename': 'tag_nextthought_com_2011-10_testing-HTML-temp_chapter_one.html',
					  'href': 'tag_nextthought_com_2011-10_testing-HTML-temp_chapter_one.html'}},
		   'NTIID': 'tag:nextthought.com,2011-10:testing-HTML-temp.0',
		   'filename': 'index.html',
		   'href': 'index.html'}},
				'href': 'index.html'}
		json_string = json.dumps(the_map)


		from nti.contentlibrary.filesystem import FilesystemKey
		from nti.contentlibrary.filesystem import FilesystemBucket


		json_key = FilesystemKey()
		json_key.absolute_path = 'assessment_index.json'
		dir_name, f_name = 'DNE', 'assessment._index.json'
		json_key.__name__ = f_name
		json_bucket = json_key.__parent__ = FilesystemBucket()
		json_bucket.absolute_path = dir_name


		from .._assignment_policy_extractor import _load_assignments
		from .._assignment_policy_extractor import _asg_registry_to_course_data
		from .._assignment_policy_extractor import _merge_disk

		registry = _load_assignments(json_string, json_key)

		ext_value = _asg_registry_to_course_data(registry)

		assert_that(ext_value, has_entry(asg_id,
										 {'Title': 'Main Title',
										  'auto_grade': {'total_points': 1},
										  'available_for_submission_beginning': '2014-01-13T00:00:00Z',
										  'available_for_submission_ending': None}) )

		# we can manually merge excluded data and auto-grade

		_merge_disk(ext_value,
					{asg_id:
					 { 'auto_grade': None,
					   'excluded': True}} )

		assert_that(ext_value, has_entry(asg_id,
										 {'Title': 'Main Title',
										  'auto_grade': None,
										  'excluded': True,
										  'available_for_submission_beginning': '2014-01-13T00:00:00Z',
										  'available_for_submission_ending': None}) )
