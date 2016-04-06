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
does_not = is_not

import os
import json

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import to_external_ntiid_oid

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver

class TestEvaluationViews(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	entry_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

	def _load_questionset(self):
		path = os.path.join(os.path.dirname(__file__), "questionset.json")
		with open(path, "r") as fp:
			result = json.load(fp)
			return result
			
	def _get_course_oid(self):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.entry_ntiid)
			course = ICourseInstance(entry)
			return to_external_ntiid_oid(course)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_simple_post(self):
		course_oid = self._get_course_oid()
		qset = self._load_questionset()
		question = to_external_object(qset['questions'][0])
		question.pop('NTIID', None)
		href = '/dataserver2/Objects/%s/CourseEvaluations' % course_oid
		res = self.testapp.post_json(href, question, status=201)
		assert_that(res.json_body, has_entry('NTIID', is_not(none())))
