#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
from nti.app.assessment.exporter import EvaluationsExporter
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

import os
import json
import fudge
from urllib import quote

from zope import component

from nti.assessment.interfaces import IQuestion

from nti.contenttypes.courses.interfaces import ICourseInstance

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

	def _load_json_resource(self, resource):
		path = os.path.join(os.path.dirname(__file__), resource)
		with open(path, "r") as fp:
			result = json.load(fp)
			return result

	def _load_questionset(self):
		return self._load_json_resource("questionset.json")

	def _load_assignment(self):
		return self._load_json_resource("assignment.json")

	def _load_assignment_no_solutions(self):
		return self._load_json_resource("assignment_no_solutions.json")

	def _get_course_oid(self):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.entry_ntiid)
			course = ICourseInstance(entry)
			return to_external_ntiid_oid(course)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_simple_ops(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		qset = self._load_questionset()
		# post
		posted = []
		for question in qset['questions']:
			res = self.testapp.post_json(href, question, status=201)
			assert_that(res.json_body, has_entry(NTIID, is_not(none())))
			posted.append(res.json_body)
		# get
		res = self.testapp.get(href, status=200)
		assert_that(res.json_body, has_entry('ItemCount', greater_than(1)))
		# put
		hrefs = []
		for question in posted:
			url = question.pop('href')
			self.testapp.put_json(url, question, status=200)
			hrefs.append(url)
		# post question set and assignment
		assignment = self._load_assignment()
		for evaluation in (qset, assignment):
			res = self.testapp.post_json(href, evaluation, status=201)
			assert_that(res.json_body, has_entry(NTIID, is_not(none())))
			hrefs.append(res.json_body['href'])
		# delete first question
		self.testapp.delete(hrefs[0], status=204)
		# items as questions
		qset = self._load_questionset()
		qset.pop('questions', None)
		questions = qset['Items'] = [p['ntiid'] for p in posted[1:]]
		res = self.testapp.post_json(href, qset, status=201)
		assert_that(res.json_body, has_entry('questions', has_length(len(questions))))

		# No submit assignment, without parts/qset.
		assignment = self._load_assignment()
		assignment.pop('parts', None)
		self.testapp.post_json(href, assignment, status=201)
		
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.entry_ntiid)
			exporter = EvaluationsExporter()
			exported = exporter.externalize(entry)
			assert_that(exported, has_entry('Items', 
											has_entry(entry.ProviderUniqueID, has_length(13))))
			
	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_assignment_no_solutions(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment_no_solutions()
		self.testapp.post_json(href, assignment, status=422)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	@fudge.patch('nti.app.assessment.evaluations.has_submissions',
				 'nti.app.assessment.views.evaluation_views.has_submissions')
	def test_change_with_subs(self, mock_ehs, mock_vhs):
		mock_ehs.is_callable().with_args().returns(False)
		mock_vhs.is_callable().with_args().returns(False)

		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		qset = self._load_questionset()
		question = qset['questions'][0]
		res = self.testapp.post_json(href, question, status=201)
		question = res.json_body

		mock_ehs.is_callable().with_args().returns(True)
		mock_vhs.is_callable().with_args().returns(True)

		url = question.pop('href')
		self.testapp.put_json(url, question, status=200)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_delete_containment(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		qset = self._load_questionset()
		res = self.testapp.post_json(href, qset, status=201)
		qset_href = res.json_body['href']
		ntiid = res.json_body['NTIID']
		# cannot delete a contained object
		question = res.json_body['questions'][0]
		href = href + '/%s' % quote(question['NTIID'])
		self.testapp.delete(href, status=422)
		# delete container
		self.testapp.delete(qset_href, status=204)
		# now delete again
		self.testapp.delete(href, status=204)
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = component.queryUtility(IQuestion, name=ntiid)
			assert_that(obj, is_(none()))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	@fudge.patch('nti.app.assessment.views.evaluation_views.has_submissions')
	def test_publish_unpublish(self, mock_vhs):
		mock_vhs.is_callable().with_args().returns(False)
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		qset = self._load_questionset()
		# post question
		question = qset['questions'][0]
		res = self.testapp.post_json(href, question, status=201)
		q_href = res.json_body['href']
		# check not registered
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			ntiid = res.json_body['NTIID']
			obj = component.queryUtility(IQuestion, name=ntiid)
			assert_that(obj.is_published(), is_(False))
		publish_href = q_href + '/@@publish'
		self.testapp.post(publish_href, status=200)
		# check registered
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = component.queryUtility(IQuestion, name=ntiid)
			assert_that(obj.is_published(), is_(True))
		# cannot unpublish w/ submissions
		unpublish_href = q_href + '/@@unpublish'
		mock_vhs.is_callable().with_args().returns(True)
		self.testapp.post(unpublish_href, status=422)
		# try w/o submissions
		mock_vhs.is_callable().with_args().returns(False)
		self.testapp.post(unpublish_href, status=200)
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = component.queryUtility(IQuestion, name=ntiid)
			assert_that(obj.is_published(), is_(False))
