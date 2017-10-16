#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

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
from six.moves.urllib_parse import quote

from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS

from nti.assessment.assignment import QAssignment

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid

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
		self.require_link_href_with_rel(ext_obj, 'schema')
		if ext_obj.get( 'MimeType' ) == QAssignment.mime_type:
			self.require_link_href_with_rel(ext_obj, 'date-edit-end')
			self.require_link_href_with_rel(ext_obj, 'date-edit-start')
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
					 contains( "application/vnd.nextthought.assessment.multiplechoicepart",
							   "application/vnd.nextthought.assessment.multiplechoicemultipleanswerpart",
							   "application/vnd.nextthought.assessment.matchingpart",
							   "application/vnd.nextthought.assessment.filepart" ))

		# QuestionSet is random for students, as well as the concrete parts.
		self._validate_random_qset_and_parts(students, qset_href, random_set=True, random_parts=True)

	def _validate_random_qset_and_parts(self, students, href, random_set=True, random_parts=True):
		"""
		For the students and href, make sure this qset is randomized, based
		on order of part mimetypes.
		"""
		question_mime_order = set()
		part_choice_order = dict()
		for student in students:
			student_env = self._make_extra_environ( username=student )
			res = self.testapp.get(href, extra_environ=student_env)
			qset = res.json_body
			student_mimes = list()
			for question in qset.get( 'questions' ):
				for part in question.get( 'parts' ):
					part_type = part.get( 'MimeType'  )
					student_mimes.append( part_type )
					if part_type == 'application/vnd.nextthought.assessment.filepart':
						continue
					ntiid = part.get( 'NTIID' )
					part_order = part_choice_order.setdefault( ntiid, set() )
					student_choice = part.get( 'values', part.get( 'choices' ))
					part_order.add( tuple( student_choice ) )
			question_mime_order.add( tuple( student_mimes ) )

		if random_set:
			assert_that( question_mime_order, has_length( greater_than( 1 )))
		else:
			assert_that( question_mime_order, has_length( 1 ))

		if random_parts:
			for choice_order in part_choice_order.values():
				assert_that( choice_order, has_length( greater_than( 1 )))
		else:
			for choice_order in part_choice_order.values():
				assert_that( choice_order, has_length( 1 ))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_randomize_sets_and_parts(self):
		"""
		Test randomize/unrandomize links. Duplicate operations do not change anything.
		"""
		students = ('student_with_no_links', 'atticus', 'declan', 'ozymandius')
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
		self._validate_random_qset_and_parts(students, qset_href, random_set=False, random_parts=False)

		# Randomize qset
		self.testapp.post( random_href )
		self.testapp.post( random_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		self.require_link_href_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)
		self._validate_random_qset_and_parts(students, qset_href, random_set=True, random_parts=False)

		# Randomize parts
		self.testapp.post( random_parts_href )
		self.testapp.post( random_parts_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)
		unrandom_href = self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		self._validate_random_qset_and_parts(students, qset_href, random_set=True, random_parts=True)

		# Unrandomize qset.
		self.testapp.post( unrandom_href )
		self.testapp.post( unrandom_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		unrandom_parts_href = self.require_link_href_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)
		self.require_link_href_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		self._validate_random_qset_and_parts(students, qset_href, random_set=False, random_parts=True)

		# Unrandomize parts
		self.testapp.post( unrandom_parts_href )
		self.testapp.post( unrandom_parts_href )
		res = self.testapp.get( qset_href )
		qset = res.json_body
		self.require_link_href_with_rel(qset, VIEW_RANDOMIZE_PARTS)
		random_href = self.require_link_href_with_rel(qset, VIEW_RANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE)
		self.forbid_link_with_rel(qset, VIEW_UNRANDOMIZE_PARTS)
		self._validate_random_qset_and_parts(students, qset_href, random_set=False, random_parts=False)

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
