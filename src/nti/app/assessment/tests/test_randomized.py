#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import not_none
from hamcrest import contains
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

import os
import json
from urllib import quote

from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.externalization import to_external_ntiid_oid

from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver

NTIID = StandardExternalFields.NTIID

class TestRandomized(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	entry_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

	def _load_json_resource(self, resource):
		path = os.path.join(os.path.dirname(__file__), resource)
		with open(path, "r") as fp:
			result = json.load(fp)
			return result

	def _load_random_questionset(self):
		return self._load_json_resource("random_questionset.json")

	def _load_questionset(self):
		return self._load_json_resource("questionset.json")

	def _get_course_oid(self):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.entry_ntiid)
			course = ICourseInstance(entry)
			return to_external_ntiid_oid(course)

	def _enroll_users(self, usernames):
		for username in usernames:
			with mock_dataserver.mock_db_trans(self.ds):
				self._create_user( username=username )
			admin_environ = self._make_extra_environ(username=self.default_username)
			enroll_url = '/dataserver2/CourseAdmin/UserCourseEnroll'
			self.testapp.post_json(enroll_url,
								  {'ntiid': self.entry_ntiid, 'username':username},
								   extra_environ=admin_environ)

	def _test_external_state(self, ext_obj, has_savepoints=False, has_submissions=False):
		self.require_link_href_with_rel(ext_obj, 'edit')
		self.require_link_href_with_rel(ext_obj, 'date-edit')
		self.require_link_href_with_rel(ext_obj, 'schema')
		limited = has_savepoints or has_submissions
		assert_that( ext_obj.get( 'LimitedEditingCapabilities' ), is_( limited ) )
		assert_that( ext_obj.get( 'LimitedEditingCapabilitiesSavepoints' ),
					 is_( has_savepoints ) )
		assert_that( ext_obj.get( 'LimitedEditingCapabilitiesSubmissions' ),
					 is_( has_submissions ) )

	def _get_qset_part_attr(self, qset, part_attr):
		"""
		For a question set, find all the attrs for all the underlying parts
		(assuming one part per question).
		"""
		questions = qset.get( 'questions' )
		result = list()
		for question in questions:
			parts = question.get( 'parts' )
			part = parts[0]
			result.append( part.get( part_attr ) )
		return tuple( result )

	def _validate_random_qset(self, students, href):
		"""
		For the students and href, make sure this qset is randomized, based
		on order of part mimetypes.
		"""
		values = set()
		for student in students:
			student_env = self._make_extra_environ( username=student )
			res = self.testapp.get(href, extra_environ=student_env)
			qset = res.json_body
			part_mimes = self._get_qset_part_attr( qset, 'MimeType' )
			values.add( part_mimes )
		assert_that( values, has_length( greater_than( 1 )))

	def _get_question_part_attr(self, question, part_attr):
		"""
		For a question, find all the attrs for all the underlying parts
		(assuming one part per question).
		"""
		parts = question.get( 'parts' )
		part = parts[0]
		values = part.get( part_attr )
		return tuple( values )

	def _validate_random_question(self, students, href, question_attr):
		"""
		For the students and href, make sure this question is randomized, based
		on order of given attr.
		"""
		values = set()
		for student in students:
			student_env = self._make_extra_environ( username=student )
			res = self.testapp.get(href, extra_environ=student_env)
			qset = res.json_body
			part_mimes = self._get_question_part_attr( qset, question_attr )
			values.add( part_mimes )
		assert_that( values, has_length( greater_than( 1 )))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_random(self):
		students = ('student11', 'student12', 'student13', 'student14')
		self._enroll_users( students )
		course_oid = self._get_course_oid()
		qset_data = self._load_random_questionset()
		evaluations_href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		res = self.testapp.post_json(evaluations_href, qset_data)
		qset = res.json_body
		creator = 'sjohnson@nextthought.com'

		# Validate instructor is not randomized.
		self._test_external_state( qset )
		questions = qset.get( 'questions' )
		for question in questions:
			self._test_external_state( question )
		qset_href = qset.get( 'href' )
		assert_that( qset_href, not_none() )
		assert_that( questions, has_length( 4 ))
		assert_that( qset.get( 'Creator' ), is_( creator ))
		part_mimes = self._get_qset_part_attr( qset, 'MimeType' )
		assert_that( part_mimes,
					 contains( "application/vnd.nextthought.assessment.randomizedmultiplechoicepart",
							   "application/vnd.nextthought.assessment.randomizedmultiplechoicemultipleanswerpart",
							   "application/vnd.nextthought.assessment.randomizedmatchingpart",
							   "application/vnd.nextthought.assessment.filepart" ))

		# But qset is
		self._validate_random_qset(students, qset_href)

		# As are the questions, if applicable.
		for question in questions:
			question_href = question.get( 'href' )
			part_type = self._get_question_part_attr( question, 'MimeType' )
			if 'randomized' not in part_type:
				continue
			part_attr = 'choices'
			if part_type == "application/vnd.nextthought.assessment.randomizedmatchingpart":
				part_attr = 'labels'
			self._validate_random_question( students, question_href, part_attr )

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_randomize_api(self):
		"""
		Test randomize/unrandomize links. Duplicate operations do not change anything.
		"""
		students = ('student_with_no_links',)
		self._enroll_users( students )
		# Upload random question set.
		course_oid = self._get_course_oid()
		qset_data = self._load_questionset()
		evaluations_href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		res = self.testapp.post_json(evaluations_href, qset_data)
		qset = res.json_body
		qset_href = qset.get( 'href' )
		random_parts_href = self.require_link_href_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		random_href = self.require_link_href_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)

		# Randomize qset
		self.testapp.post( random_href )
		self.testapp.post( random_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		self.require_link_href_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)

		# Randomize parts
		self.testapp.post( random_parts_href )
		self.testapp.post( random_parts_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)
		unrandom_href = self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE_PARTS)

		# Unrandomize qset.
		self.testapp.post( unrandom_href )
		self.testapp.post( unrandom_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		unrandom_parts_href = self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)
		self.require_link_href_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE_PARTS)

		# Unrandomize parts
		self.testapp.post( unrandom_parts_href )
		self.testapp.post( unrandom_parts_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		self.require_link_href_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		random_href = self.require_link_href_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)

		rel_list = (VIEW_UNRANDOMIZE, VIEW_RANDOMIZE, VIEW_RANDOMIZE_PARTS, VIEW_UNRANDOMIZE_PARTS)
		# Students have none
		student_env = self._make_extra_environ( username=students[0] )
		res = self.testapp.get(qset_href, extra_environ=student_env)
		student_res = res.json_body
		for rel in rel_list:
			self.forbid_link_with_rel(student_res, rel)
		self.testapp.post( unrandom_parts_href, extra_environ=student_env, status=403 )
		self.testapp.post( random_parts_href, extra_environ=student_env, status=403 )
		self.testapp.post( random_href, extra_environ=student_env, status=403 )
		self.testapp.post( unrandom_href, extra_environ=student_env, status=403 )

		# Synced question set has no such links as well.
		assignment_id = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'
		res = self.testapp.get( '/dataserver2/Objects/%s' % assignment_id )
		res = res.json_body
		synced_qset = res.get( 'parts' )[0].get( 'question_set' )
		synced_qset_href = synced_qset.get( 'href' )
		for rel in rel_list:
			self.forbid_link_with_rel(synced_qset, rel)
			self.testapp.post( '%s/@@%s' % (synced_qset_href, rel), status=422 )
