#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import none
from hamcrest import is_not
from hamcrest import has_entry
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

import os
import json

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import to_external_ntiid_oid

from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver

NTIID = StandardExternalFields.NTIID

class TestEvaluationViews(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	entry_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

	def _load_questionset(self):
		path = os.path.join(os.path.dirname(__file__), "questionset.json")
		with open(path, "r") as fp:
			result = json.load(fp)
			return result

	def _load_assignment(self):
		path = os.path.join(os.path.dirname(__file__), "assignment.json")
		with open(path, "r") as fp:
			result = json.load(fp)
			return result

	def _get_course_oid(self):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.entry_ntiid)
			course = ICourseInstance(entry)
			return to_external_ntiid_oid(course)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_simple_ops(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % course_oid
		qset = self._load_questionset()
		# post
		posted = []
		for question in qset['questions']:
			question = to_external_object(question)
			res = self.testapp.post_json(href, question, status=201)
			assert_that(res.json_body, has_entry(NTIID, is_not(none())))
			posted.append(res.json_body)
		# get
		res = self.testapp.get(href, status=200)
		assert_that(res.json_body, has_entry('ItemCount', greater_than(1)))
		# put
		for question in posted:
			url = question.pop('href')
			self.testapp.put_json(url, question, status=200)
		# post question set and assignment
		assignment = self._load_assignment()
		for evaluation in (qset, assignment):
			evaluation = to_external_object(evaluation)
			res = self.testapp.post_json(href, evaluation, status=201)
			assert_that(res.json_body, has_entry(NTIID, is_not(none())))