#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import contains
from hamcrest import not_none
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

from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS

from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations.exporter import EvaluationsExporter

from nti.assessment.interfaces import IQuestion

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.externalization import to_external_ntiid_oid

from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver

from nti.recorder.interfaces import ITransactionRecordHistory

from nti.testing.time import time_monotonically_increases

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

	def _test_assignments(self, assessment_ntiid, assignment_ntiids=()):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = find_object_with_ntiid( assessment_ntiid )
			assignments = get_assignments_for_evaluation_object( obj )
			found_ntiids = tuple(x.ntiid for x in assignments)
			assert_that( found_ntiids, is_(assignment_ntiids))

	def _test_external_state(self, ext_obj, available=False, has_savepoints=False, has_submissions=False):
		# TODO: test with submissions/savepoints.
		self.require_link_href_with_rel(ext_obj, 'edit')
		self.require_link_href_with_rel(ext_obj, 'date-edit')
		self.require_link_href_with_rel(ext_obj, 'schema')
		limited = has_savepoints or has_submissions or available
		assert_that( ext_obj.get( 'LimitedEditingCapabilities' ), is_( limited ) )
		assert_that( ext_obj.get( 'LimitedEditingCapabilitiesSavepoints' ),
					 is_( has_savepoints ) )
		assert_that( ext_obj.get( 'LimitedEditingCapabilitiesSubmissions' ),
					 is_( has_submissions ) )

	def _test_qset_ext_state(self, qset, creator, assignment_ntiid, **kwargs):
		self._test_assignments( qset.get( NTIID ), assignment_ntiids=(assignment_ntiid,) )
		self._test_external_state( qset, **kwargs )
		assert_that( qset.get( "Creator" ), is_(creator) )
		assert_that( qset.get( NTIID ), not_none() )
		for question in qset.get( 'questions' ):
			question_ntiid = question.get( NTIID )
			assert_that( question.get( "Creator" ), is_(creator) )
			assert_that( question_ntiid, not_none() )
			self._test_assignments( question_ntiid, assignment_ntiids=(assignment_ntiid,) )
			self._test_external_state( question, **kwargs )

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_creating_assessments(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		qset = self._load_questionset()
		creator = 'sjohnson@nextthought.com'

		# post
		posted = []
		for question in qset['questions']:
			res = self.testapp.post_json(href, question, status=201)
			assert_that( res.json_body.get( 'Creator' ), not_none() )
			assert_that(res.json_body, has_entry(NTIID, not_none()))
			self._test_external_state( res.json_body )
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

		# Edit question
		self.testapp.put_json(url, {'content': 'blehcontent'})

		# Post (unpublished) assignment
		assignment = self._load_assignment()
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		self._test_external_state( res )
		assignment_ntiid = res.get( NTIID )
		assignment_href = res['href']
		assert_that(assignment_ntiid, not_none())
		hrefs.append(assignment_href)
		assert_that( res.get( "Creator" ), is_(creator) )
		for part in res.get( 'parts' ):
			part_qset = part.get( 'question_set' )
			qset_href = part_qset.get( 'href' )
			assert_that( qset_href, not_none() )
			self._test_qset_ext_state( part_qset, creator, assignment_ntiid, available=False )

		# Now publish; items are available since they are in a published assignment.
		self.testapp.post( '%s/@@publish' % assignment_href )
		part_qset = self.testapp.get( qset_href )
		part_qset = part_qset.json_body
		self._test_qset_ext_state( part_qset, creator, assignment_ntiid, available=True )

		# Post qset
		res = self.testapp.post_json(href, qset, status=201)
		res = res.json_body
		assert_that(res, has_entry(NTIID, not_none()))
		hrefs.append(res['href'])
		qset_ntiid = res.get( NTIID )
		assert_that( res.get( "Creator" ), is_(creator) )
		assert_that( qset_ntiid, not_none() )
		self._test_assignments( qset_ntiid )
		self._test_external_state( res )
		for question in res.get( 'questions' ):
			question_ntiid = question.get( NTIID )
			assert_that( question.get( "Creator" ), is_(creator) )
			assert_that( question_ntiid, not_none() )
			self._test_assignments( question_ntiid )
			self._test_external_state( question )

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
			assert_that(exported, has_entry('Items', has_length(13)))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_editing_assignments(self):
		editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		# Make assignment empty, without questions
		assignment = self._load_assignment()
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		assignment_ntiid = res.get( 'ntiid' )
		qset = res.get( 'parts' )[0].get( 'question_set' )
		qset_contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)
		question_ntiid = qset.get( 'questions' )[0].get( 'ntiid' )
		delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
		self.testapp.delete(qset_contents_href + delete_suffix)

		# Test editing auto_grade/points.
		data = { 'total_points': 100 }
		self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  data, extra_environ=editor_environ)
		res = self.testapp.get('/dataserver2/Objects/' + assignment_ntiid,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get('auto_grade'), none())
		assert_that(res.get('total_points'), is_(100))

		data = { 'auto_grade': False, 'total_points': 5 }
		self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  data, extra_environ=editor_environ)
		res = self.testapp.get('/dataserver2/Objects/' + assignment_ntiid,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get('auto_grade'), is_(False))
		assert_that(res.get('total_points'), is_(5))

		data = { 'auto_grade': 'true', 'total_points': 500 }
		self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  data, extra_environ=editor_environ)
		res = self.testapp.get('/dataserver2/Objects/' + assignment_ntiid,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get('auto_grade'), is_(True))
		assert_that(res.get('total_points'), is_(500))

		data = { 'auto_grade': 'false', 'total_points': 2.5 }
		self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  data, extra_environ=editor_environ)
		res = self.testapp.get('/dataserver2/Objects/' + assignment_ntiid,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get('auto_grade'), is_(False))
		assert_that(res.get('total_points'), is_(2.5))

		# Errors
		data = { 'auto_grade': 'what', 'total_points': 2.5 }
		res = self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  		data, extra_environ=editor_environ,
							  		status=422)
		assert_that( res.json_body.get( 'field' ), is_( 'auto_grade' ))

		data = { 'auto_grade': 10, 'total_points': 2.5 }
		res = self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  		data, extra_environ=editor_environ,
							  		status=422)
		assert_that( res.json_body.get( 'field' ), is_( 'auto_grade' ))

		data = { 'auto_grade': 'True', 'total_points': -1 }
		res = self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  		data, extra_environ=editor_environ,
							  		status=422)
		assert_that( res.json_body.get( 'field' ), is_( 'total_points' ))

		data = { 'auto_grade': 'True', 'total_points': 'bleh' }
		res = self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  		data, extra_environ=editor_environ,
							  		status=422)
		assert_that( res.json_body.get( 'field' ), is_( 'total_points' ))

		# Validated auto-grading state.
		data = { 'auto_grade': 'True' }
		self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  data, extra_environ=editor_environ)

		# Add gradable question when auto-grade enabled.
		qset_source = self._load_questionset()
		gradable_question = qset_source.get( 'questions' )[0]
		self.testapp.post_json(qset_contents_href, gradable_question)

		# File part non-gradable cannot be added.
		file_question = {'Class': 'Question',
					'MimeType': 'application/vnd.nextthought.naquestion',
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
		res = self.testapp.post_json(qset_contents_href, file_question, status=422)
		assert_that( res.json_body.get( 'code' ), is_('UngradableInAutoGradeAssignment'))

		# Turn off auto-grade and add file part
		data = { 'auto_grade': 'False' }
		self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							  data, extra_environ=editor_environ)
		self.testapp.post_json(qset_contents_href, file_question)

		# Now enabling auto-grading fails.
		data = { 'auto_grade': 'True' }
		res = self.testapp.put_json('/dataserver2/Objects/%s' % assignment_ntiid,
							 		 data, extra_environ=editor_environ,
							 		 status=422)
		assert_that( res.json_body.get( 'code' ), is_('UngradableInAutoGradeAssignment'))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_part_validation(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment()
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		qset = res.get( 'parts' )[0].get( 'question_set' )
		qset_contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)

		question_set = self._load_questionset()
		questions = question_set.get( 'questions' )
		multiple_choice = questions[0]
		multiple_answer = questions[1]
		matching = questions[2]

		# Multiple choice
		dupes = ['1','2','3','1']
		empties = [ 'test', 'empty', '', 'try']
		dupe_index = 3
		empty_index = 2

		# Multiple choice duplicates
		multiple_choice['parts'][0]['choices'] = dupes
		res = self.testapp.post_json( qset_contents_href, multiple_choice, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'choices' ))
		assert_that( res.get( 'index' ), contains( dupe_index ))

		# Multiple choice empty
		multiple_choice['parts'][0]['choices'] = empties
		res = self.testapp.post_json( qset_contents_href, multiple_choice, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'choices' ))
		assert_that( res.get( 'index' ), contains( empty_index ))

		# Multiple answer duplicates
		multiple_answer['parts'][0]['choices'] = dupes
		res = self.testapp.post_json( qset_contents_href, multiple_answer, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'choices' ))
		assert_that( res.get( 'index' ), contains( dupe_index ))

		# Multiple answer empty
		multiple_answer['parts'][0]['choices'] = empties
		res = self.testapp.post_json( qset_contents_href, multiple_answer, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'choices' ))
		assert_that( res.get( 'index' ), contains( empty_index ))

		# Matching duplicate labels
		old_labels = matching['parts'][0]['labels']
		matching['parts'][0]['labels'] = dupes
		res = self.testapp.post_json( qset_contents_href, matching, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'labels' ))
		assert_that( res.get( 'index' ), contains( dupe_index ))

		# Matching empty labels
		matching['parts'][0]['labels'] = empties
		res = self.testapp.post_json( qset_contents_href, matching, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'labels' ))
		assert_that( res.get( 'index' ), contains( empty_index ))

		# Matching duplicate values
		matching['parts'][0]['labels'] = old_labels
		matching['parts'][0]['values'] = dupes
		res = self.testapp.post_json( qset_contents_href, matching, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'values' ))
		assert_that( res.get( 'index' ), contains( dupe_index ))

		# Matching empty values
		matching['parts'][0]['values'] = empties
		res = self.testapp.post_json( qset_contents_href, matching, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'values' ))
		assert_that( res.get( 'index' ), contains( empty_index ))

		# Matching multiple duplicates
		matching['parts'][0]['values'] = ['1','2','1','3','3','1']
		res = self.testapp.post_json( qset_contents_href, matching, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'values' ))
		assert_that( res.get( 'index' ), contains( 2, 4, 5 ))

		# Matching unequal count
		matching['parts'][0]['values'] = dupes[:-1]
		res = self.testapp.post_json( qset_contents_href, matching, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'values' ))
		assert_that( res.get( 'code' ), is_( 'InvalidLabelsValues' ))

	@time_monotonically_increases
	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_assignment_versioning(self):
		"""
		Validate various edits bump an assignments version and
		may not be allowed if there are submissions.
		"""
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment()
		question_set_source = self._load_questionset()
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		assignment_href = res.get( 'href' )
		assert_that( res.get( 'version' ), none() )
		qset = res.get( 'parts' )[0].get( 'question_set' )
		qset_ntiid = qset.get( 'NTIID' )
		qset_href = qset.get( 'href' )
		qset_move_href = self.require_link_href_with_rel(qset, VIEW_ASSESSMENT_MOVE)
		qset_contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)

		def _check_version( old_version=None ):
			"Validate assigment version has changed"
			assignment_res = self.testapp.get( assignment_href )
			new_version = assignment_res.json_body.get( 'version' )
			assert_that( new_version, is_not( old_version ))
			assert_that( new_version, not_none() )
			return new_version

		# Delete a question
		question_ntiid = qset.get( 'questions' )[0].get( 'ntiid' )
		delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
		self.testapp.delete(qset_contents_href + delete_suffix)
		version = _check_version()

		# Add three questions
		for question in question_set_source.get('questions'):
			new_question = self.testapp.post_json( qset_contents_href, question )
			new_question = new_question.json_body
			question_ntiid = new_question.get( "NTIID" )
			version = _check_version( version )

		# Move a question
		move_json = self._get_move_json( question_ntiid, qset_ntiid, 0 )
		self.testapp.post_json( qset_move_href, move_json )
		version = _check_version( version )

		# Edit question part
# 		multiple_choice['parts'][0]['choices'] = old_choices
# 		res = self.testapp.post_json( qset_contents_href, multiple_choice )
# 		res = res.json_body
# 		first_question = res
# 		first_href = first_question.get( 'href' )
# 		first_part = first_question.get( 'parts' )[0]
# 		first_part['choices'] = ['new', 'old', 'different']
# 		res = self.testapp.put_json( first_href, first_question )

		# FIXME: Part changes

		# Test randomization
		# Order is important
		rel_list = (VIEW_RANDOMIZE, VIEW_RANDOMIZE_PARTS, VIEW_UNRANDOMIZE, VIEW_UNRANDOMIZE_PARTS)
		for rel in rel_list:
			new_qset = self.testapp.get( qset_href )
			new_qset = new_qset.json_body
			random_link = self.require_link_href_with_rel(new_qset, rel)
			self.testapp.post( random_link )
			version = _check_version( version )

		# FIXME: test submissions

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_assignment_no_solutions(self):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment_no_solutions()
		self.testapp.post_json(href, assignment, status=422)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	@fudge.patch('nti.app.assessment.evaluations.subscribers.has_submissions',
				 'nti.app.assessment.evaluations.utils.has_submissions')
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

# 		url = question.pop('href')
# 		self.testapp.put_json(url, question, status=200)

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
	@fudge.patch('nti.app.assessment.evaluations.utils.has_submissions')
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

	def _get_move_json(self, obj_ntiid, new_parent_ntiid, index=None, old_parent_ntiid=None):
		result = {  'ObjectNTIID': obj_ntiid,
					'ParentNTIID': new_parent_ntiid }
		if index is not None:
			result['Index'] = index
		if old_parent_ntiid is not None:
			result['OldParentNTIID'] = old_parent_ntiid
		return result

	def _test_transaction_history(self, ntiid, count=0):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = find_object_with_ntiid( ntiid )
			assert_that( obj, not_none() )
			history = ITransactionRecordHistory(obj)
			record_types = [x.type for x in history.records()]
			assert_that(record_types, has_length(count))

	def _get_question_ntiids(self, ntiid=None, ext_obj=None):
		"""
		For the given ntiid or ext_obj (of assignment or question set),
		return all of the underlying question ntiids.
		"""
		if not ext_obj:
			res = self.testapp.get( '/dataserver2/Objects/%s' % ntiid )
			ext_obj = res.json_body
		if ext_obj.get( 'Class' ) != 'QuestionSet':
			ext_obj = ext_obj.get( 'parts' )[0].get( 'question_set' )
		questions = ext_obj.get( 'questions' )
		return [x.get( 'NTIID' ) for x in questions]

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_move(self):
		"""
		Test moving questions within question sets.
		"""
		# Initialize and install qset and one assignments.
		course_oid = self._get_course_oid()
		course = self.testapp.get( '/dataserver2/Objects/%s' % course_oid )
		course = course.json_body
		evaluations_href = self.require_link_href_with_rel(course, 'CourseEvaluations')
		qset = self._load_questionset()
		qset = self.testapp.post_json(evaluations_href, qset, status=201)
		qset_ntiid = qset.json_body.get( 'NTIID' )
		move_href = self.require_link_href_with_rel(qset.json_body, VIEW_ASSESSMENT_MOVE)
		qset_question_ntiids = self._get_question_ntiids(ext_obj=qset.json_body)
		assignment = self._load_assignment()
		assignment1 = self.testapp.post_json(evaluations_href, assignment, status=201)
		assignment1 = assignment1.json_body
		qset2 = assignment1.get( 'parts' )[0].get( 'question_set' )
		qset2_ntiid = qset2.get( 'NTIID' )
		qset2_move_href = self.require_link_href_with_rel(qset2, VIEW_ASSESSMENT_MOVE)

		# Move last question to first.
		moved_ntiid = qset_question_ntiids[-1]
		move_json = self._get_move_json( moved_ntiid, qset_ntiid, 0 )
		self.testapp.post_json( move_href, move_json )
		new_question_ntiids = self._get_question_ntiids( qset_ntiid )
		assert_that( new_question_ntiids, is_(qset_question_ntiids[-1:] + qset_question_ntiids[:-1]))
		self._test_transaction_history( moved_ntiid, count=1 )

		# Move back
		move_json = self._get_move_json( moved_ntiid, qset_ntiid )
		self.testapp.post_json( move_href, move_json )
		new_question_ntiids = self._get_question_ntiids( qset_ntiid )
		assert_that( new_question_ntiids, is_(qset_question_ntiids))
		self._test_transaction_history( moved_ntiid, count=2 )

		# Move within a question set invalid.
		dne_ntiid = qset_ntiid + 'xxx'
		move_json = self._get_move_json( moved_ntiid, dne_ntiid, index=1 )
		self.testapp.post_json( move_href, move_json, status=422 )

		# Ntiid does not exist in qset2.
		move_json = self._get_move_json( moved_ntiid, qset2_ntiid,
										 index=1, old_parent_ntiid=dne_ntiid )
		self.testapp.post_json( qset2_move_href, move_json, status=422 )

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_insert(self):
		"""
		Test moving questions between question sets.
		"""
		# Initialize and install qset
		course_oid = self._get_course_oid()
		course = self.testapp.get( '/dataserver2/Objects/%s' % course_oid )
		course = course.json_body
		evaluations_href = self.require_link_href_with_rel(course, 'CourseEvaluations')
		qset = self._load_questionset()
		ext_question = qset.get( 'questions' )[0]
		qset = self.testapp.post_json(evaluations_href, qset, status=201)
		qset = qset.json_body
		contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)
		qset_ntiid = qset.get( 'NTIID' )
		original_question_ntiids = self._get_question_ntiids(ext_obj=qset)

		# Insert/append
		inserted_question = self.testapp.post_json(contents_href, ext_question)
		new_question_ntiid = inserted_question.json_body.get( 'NTIID' )
		question_ntiids = self._get_question_ntiids( qset_ntiid )
		assert_that( question_ntiids, is_(original_question_ntiids + [new_question_ntiid]) )

		# Prepend
		inserted_question = self.testapp.post_json(contents_href + '/index/0', ext_question)
		new_question_ntiid2 = inserted_question.json_body.get( 'NTIID' )
		question_ntiids = self._get_question_ntiids( qset_ntiid )
		assert_that( question_ntiids, is_([new_question_ntiid2] + original_question_ntiids + [new_question_ntiid]) )

	def _get_delete_url_suffix(self, index, ntiid):
		return '/ntiid/%s?index=%s' % (ntiid, index)

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_delete(self):
		"""
		Test deleting by index/ntiid in question sets.
		"""
		# Initialize and install qset
		course_oid = self._get_course_oid()
		course = self.testapp.get( '/dataserver2/Objects/%s' % course_oid )
		course = course.json_body
		evaluations_href = self.require_link_href_with_rel(course, 'CourseEvaluations')
		qset = self._load_questionset()
		ext_question = qset.get( 'questions' )[0]
		qset = self.testapp.post_json(evaluations_href, qset, status=201)
		qset = qset.json_body
		contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)
		qset_ntiid = qset.get( 'NTIID' )
		original_question_ntiids = self._get_question_ntiids(ext_obj=qset)

		# Insert/append
		inserted_question = self.testapp.post_json(contents_href, ext_question)
		new_question_ntiid = inserted_question.json_body.get( 'NTIID' )
		question_ntiids = self._get_question_ntiids( qset_ntiid )
		assert_that( question_ntiids, is_(original_question_ntiids + [new_question_ntiid]) )

		# Now delete (incorrect index).
		delete_suffix = self._get_delete_url_suffix(0, new_question_ntiid)
		self.testapp.delete(contents_href + delete_suffix)
		assert_that( self._get_question_ntiids( qset_ntiid ), is_(original_question_ntiids) )
		# No problem with multiple calls
		self.testapp.delete(contents_href + delete_suffix)
		assert_that( self._get_question_ntiids( qset_ntiid ), is_(original_question_ntiids) )

		# Delete first object
		delete_suffix = self._get_delete_url_suffix(0, original_question_ntiids[0])
		self.testapp.delete(contents_href + delete_suffix)
		assert_that( self._get_question_ntiids( qset_ntiid ), is_(original_question_ntiids[1:]) )
