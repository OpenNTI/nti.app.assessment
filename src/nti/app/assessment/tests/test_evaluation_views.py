#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import contains
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
from hamcrest import has_property
from hamcrest import contains_inanyorder
does_not = is_not

import os
import json
import time
import fudge
from urllib import quote

from zope import component

from zope.intid.interfaces import IIntIds

from nti.app.assessment import get_evaluation_catalog

from nti.app.assessment import VIEW_MOVE_PART
from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_INSERT_PART
from nti.app.assessment import VIEW_REMOVE_PART
from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_MOVE_PART_OPTION
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS
from nti.app.assessment import VIEW_INSERT_PART_OPTION
from nti.app.assessment import VIEW_REMOVE_PART_OPTION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS
from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations.exporter import EvaluationsExporter

from nti.app.assessment.index import IX_NTIID
from nti.app.assessment.index import IX_MIMETYPE

from nti.assessment.interfaces import QUESTION_MIME_TYPE
from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE
from nti.assessment.interfaces import QUESTION_BANK_MIME_TYPE

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQuestionSet

from nti.assessment.response import QUploadedFile

from nti.assessment.submission import QuestionSubmission
from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.assessment.randomized.interfaces import IQuestionBank

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.externalization import toExternalObject
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

	def _test_external_state(self, ext_obj=None, ntiid=None, available=False,
							 has_savepoints=False, has_submissions=False):
		"""
		Test the external state of the given ext_obj or ntiid. We test that
		status changes based on submissions and other user interaction.
		"""
		if not ext_obj:
			ext_obj = self.testapp.get( '/dataserver2/Objects/%s' % ntiid ).json_body
		self.require_link_href_with_rel(ext_obj, 'date-edit')
		limited = has_savepoints or has_submissions or available
		assert_that( ext_obj.get( 'LimitedEditingCapabilities' ), is_( limited ) )
		assert_that( ext_obj.get( 'LimitedEditingCapabilitiesSavepoints' ),
					 is_( has_savepoints ) )
		assert_that( ext_obj.get( 'LimitedEditingCapabilitiesSubmissions' ),
					 is_( has_submissions ) )

		# We always have schema and edit rels.
		for rel in ('schema', 'edit'):
			self.require_link_href_with_rel(ext_obj, rel)

		# We drive these links based on the submission status of objects.
		submission_rel_checks = []
		to_check = self.forbid_link_with_rel if has_submissions else self.require_link_href_with_rel
		ext_mime = ext_obj.get( 'MimeType' )
		if ext_mime == QUESTION_MIME_TYPE:
			submission_rel_checks.extend( (VIEW_MOVE_PART,
									 	   VIEW_INSERT_PART,
									 	   VIEW_REMOVE_PART,
									 	   VIEW_MOVE_PART_OPTION,
									 	   VIEW_INSERT_PART_OPTION,
									 	   VIEW_REMOVE_PART_OPTION) )
		elif ext_mime == ASSIGNMENT_MIME_TYPE:
			submission_rel_checks.extend( (VIEW_MOVE_PART,
										   VIEW_INSERT_PART,
										   VIEW_REMOVE_PART) )
		elif ext_mime == QUESTION_SET_MIME_TYPE:
			# Randomize is context sensitive and tested elsewhere.
			submission_rel_checks.extend( (VIEW_QUESTION_SET_CONTENTS,
										   VIEW_ASSESSMENT_MOVE) )

		for rel in submission_rel_checks:
			to_check( ext_obj, rel )

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
		qset_href = res.json_body['href']
		qset_ntiid = res.json_body['NTIID']
		assert_that( qset_ntiid, not_none() )

		# No submit assignment, without parts/qset.
		assignment = self._load_assignment()
		assignment.pop('parts', None)
		self.testapp.post_json(href, assignment, status=201)

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.entry_ntiid)
			exporter = EvaluationsExporter()
			exported = exporter.externalize(entry)
			assert_that(exported, has_entry('Items', has_length(13)))

		copy_ref = qset_href + '/@@Copy'
		res = self.testapp.post(copy_ref, status=201)
		assert_that(res.json_body, has_entry('NTIID', is_not(qset_ntiid)) )

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
	def test_question_bank_toggle(self):
		"""
		Test toggling a question set to/from question bank.
		"""
		course_oid = self._get_course_oid()
		assignment = self._load_assignment()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		assignment_ntiid = res.get( NTIID )
		original_res = res.get( 'parts' )[0].get( 'question_set' )
		qset_ntiid = original_res.get( 'ntiid' )
		qset_href = '/dataserver2/Objects/%s' % qset_ntiid
		unchanging_keys = ('Creator','CreatedTime', 'title', 'ntiid')

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			self._test_transaction_history( qset_ntiid, count=0 )

		# Convert to question bank
		draw_count = 3
		data = { 'draw': 3 }
		res = self.testapp.put_json( qset_href, data )

		res = self.testapp.get( qset_href )
		res = res.json_body
		# Class is always question set.
		assert_that( res.get( 'Class' ), is_( 'QuestionSet' ) )
		assert_that( res.get( 'MimeType' ), is_( QUESTION_BANK_MIME_TYPE ) )
		assert_that( res.get( 'draw' ), is_( draw_count ) )
		assert_that( res.get( 'ranges' ), has_length( 0 ) )
		for key in unchanging_keys:
			assert_that( res.get( key ), is_( original_res.get( key )), key )

		def _get_question_banks():
			cat = get_evaluation_catalog()
			timed_objs = tuple( cat.apply(
									{IX_MIMETYPE:
										{'any_of': (QUESTION_BANK_MIME_TYPE,)}}))
			return timed_objs

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			qset = find_object_with_ntiid( qset_ntiid )
			obj = component.queryUtility( IQuestionBank, name=qset_ntiid )
			assert_that( obj, not_none() )
			assert_that( obj.ntiid, is_( qset_ntiid ))
			assert_that( obj, is_( qset ))
			intids = component.getUtility(IIntIds)
			obj_id = intids.getId( obj )
			# Validate index
			catalog = get_evaluation_catalog()
			rs = catalog.get( IX_NTIID ).values_to_documents.get( qset_ntiid )
			assert_that( rs, contains( obj_id ))

			question_banks = _get_question_banks()
			assert_that( question_banks, has_item( obj_id ))
			# TODO: No create record?
			self._test_transaction_history( qset_ntiid, count=1 )
			# Validate assignment ref.
			assignment = find_object_with_ntiid( assignment_ntiid )
			assignment_qset = assignment.parts[0].question_set
			assert_that( intids.getId( assignment_qset ), is_( obj_id ))

		# Convert back to question set
		data = { 'draw': None }
		self.testapp.put_json( qset_href, data )
		res = self.testapp.get( qset_href )
		res = res.json_body
		assert_that( res.get( 'Class' ), is_( 'QuestionSet' ) )
		assert_that( res.get( 'MimeType' ), is_( QUESTION_SET_MIME_TYPE ) )
		assert_that( res.get( 'draw' ), none() )
		assert_that( res.get( 'ranges' ), none() )
		for key in unchanging_keys:
			assert_that( res.get( key ), is_( original_res.get( key )), key )

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			qset = find_object_with_ntiid( qset_ntiid )
			obj = component.queryUtility( IQuestionBank, name=qset_ntiid )
			assert_that( obj, none() )
			obj = component.queryUtility( IQuestionSet, name=qset_ntiid )
			assert_that( obj, not_none() )
			assert_that( obj.ntiid, is_( qset_ntiid ))
			assert_that( obj, is_( qset ))
			intids = component.getUtility(IIntIds)
			obj_id = intids.getId( obj )

			# Validate index
			catalog = get_evaluation_catalog()
			rs = catalog.get( IX_NTIID ).values_to_documents.get( qset_ntiid )
			assert_that( rs, contains( obj_id ))

			question_banks = _get_question_banks()
			assert_that( question_banks, does_not( has_item( obj_id )))

			self._test_transaction_history( qset_ntiid, count=2 )

			# Validate assignment ref.
			assignment = find_object_with_ntiid( assignment_ntiid )
			assignment_qset = assignment.parts[0].question_set
			assert_that( intids.getId( assignment_qset ), is_( obj_id ))

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
		# Clients may have html wrapped dupes
		html_dupes = ['1', '2',
					  '<a data-id="data-id111"></a>Choice 1',
					  '<a data-id="data-id222"></a>Choice 1' ]
		empties = [ 'test', 'empty', '', 'try']
		dupe_index = 3
		html_dupe_index = 3
		empty_index = 2

		# Multiple choice duplicates
		multiple_choice['parts'][0]['choices'] = html_dupes
		res = self.testapp.post_json( qset_contents_href, multiple_choice, status=422 )
		res = res.json_body
		assert_that( res.get( 'field' ), is_( 'choices' ))
		assert_that( res.get( 'index' ), contains( html_dupe_index ))

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

	def _validate_assignment_containers( self, obj_ntiid, assignment_ntiids=() ):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = find_object_with_ntiid( obj_ntiid )
			assignments = get_assignments_for_evaluation_object( obj )
			found_ntiids = [x.ntiid for x in assignments or ()]
			assert_that( found_ntiids, contains_inanyorder( *assignment_ntiids ))

	def _test_version_submission(self, submit_href, savepoint_href, submission,
								 new_version, old_version=None):
		"""
		Test submissions with versions.
		"""
		# We do this by doing the PracticeSubmission with instructor, which does not
		# persist. We savepoint with instructor even though the link is not available.
		submission = toExternalObject( submission )
		hrefs = (submit_href, savepoint_href)
		if old_version:
			# All 409s if we post no version or old version on an assignment with version.
			submission.pop( 'version', None )
			for href in hrefs:
				self.testapp.post_json( href, submission, status=409 )
			submission['version'] = None
			for href in hrefs:
				self.testapp.post_json( href, submission, status=409 )
			submission['version'] = old_version
			for href in hrefs:
				self.testapp.post_json( href, submission, status=409 )
		if not new_version:
			# Assignment has no version, post with nothing is ok too.
			submission.pop( 'version', None )
			for href in hrefs:
				self.testapp.post_json( href, submission )
		submission['version'] = new_version
		# XXX: We are not testing assessed results...
		for href in hrefs:
			self.testapp.post_json( href, submission )

	def _create_and_enroll(self, username):
		with mock_dataserver.mock_db_trans(self.ds):
			self._create_user( username=username )
		environ = self._make_extra_environ( username=username )
		admin_environ = self._make_extra_environ(username=self.default_username)
		enroll_url = '/dataserver2/CourseAdmin/UserCourseEnroll'
		self.testapp.post_json(enroll_url,
							  {'ntiid': self.entry_ntiid,
							   'username':username},
							   extra_environ=admin_environ)
		return environ

	@time_monotonically_increases
	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_assignment_versioning(self):
		"""
		Validate various edits bump an assignments version and
		may not be allowed if there are submissions.

		XXX: AssignmentParts set below are not auto_grade...

		FIXME: Assignment/Q part reorder (need part ntiids?)
		"""
		# Create base assessment object, enroll student, and set up vars for test.
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment()
		question_set_source = self._load_questionset()
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		assignment_href = res.get( 'href' )
		assignment_submit_href = self.require_link_href_with_rel( res,
																  ASSESSMENT_PRACTICE_SUBMISSION)
		assignment_ntiid = res.get('ntiid')
		assignment_ntiids = (assignment_ntiid,)
		savepoint_href = '/dataserver2/Objects/%s/AssignmentSavepoints/sjohnson@nextthought.com/%s/Savepoint' % \
						 (course_oid, assignment_ntiid )
		assert_that( res.get( 'version' ), none() )
		old_part = res.get( 'parts' )[0]
		qset = old_part.get( 'question_set' )
		# Must have at least one question...
		new_part = {"Class": "AssignmentPart",
					"MimeType": "application/vnd.nextthought.assessment.assignmentpart",
					"auto_grade": False,
					"content": "",
					"question_set": {
						"Class": "QuestionSet",
						"MimeType": "application/vnd.nextthought.naquestionset",
						"questions": [question_set_source.get('questions')[0],]
					}
				}
		qset_ntiid = qset.get( 'NTIID' )
		qset_href = qset.get( 'href' )
		question_ntiid = qset.get( 'questions' )[0].get( 'ntiid' )
		qset_move_href = self.require_link_href_with_rel(qset, VIEW_ASSESSMENT_MOVE)
		qset_contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)
		self._validate_assignment_containers( qset_ntiid, assignment_ntiids )

		# Get submission ready
		upload_submission = QUploadedFile(data=b'1234',
										  contentType=b'image/gif',
										  filename='foo.pdf')
		q_sub = QuestionSubmission(questionId=question_ntiid,
								   parts=(upload_submission,))

		qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
											  questions=(q_sub,))
		submission = AssignmentSubmission(assignmentId=assignment_ntiid,
										  parts=(qs_submission,))
		self._test_version_submission( assignment_submit_href, savepoint_href, submission, None )

		def _check_version( old_version=None, changed=True ):
			"Validate assignment version has changed and return the new version."
			to_check = is_not if changed else is_
			assignment_res = self.testapp.get( assignment_href )
			new_version = assignment_res.json_body.get( 'version' )
			assert_that( new_version, to_check( old_version ))
			assert_that( new_version, not_none() )
			return new_version, old_version

		# Delete a question
		delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
		self.testapp.delete(qset_contents_href + delete_suffix)
		version, _ = _check_version()
		# No assignments for ntiid
		self._validate_assignment_containers( question_ntiid )

		# Add three questions
		question_submissions = []
		questions = question_set_source.get('questions')
		# XXX: Skip file upload question
		for question in questions[:-1]:
			new_question = self.testapp.post_json( qset_contents_href, question )
			new_question = new_question.json_body
			question_mime = new_question.get( 'MimeType' )
			solution = ('0',)
			if 'matchingpart' in question_mime:
				solution = ({'0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6},)
			elif 'filepart' in question_mime:
				solution = (upload_submission,)
			new_submission = QuestionSubmission(questionId=new_question.get( 'NTIID' ),
								   				parts=solution)
			question_submissions.append( new_submission )
			version, old_version = _check_version( version )
			qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
											      questions=question_submissions)
			submission = AssignmentSubmission(assignmentId=assignment_ntiid,
										  	  parts=(qs_submission,))
			self._test_version_submission( assignment_submit_href, savepoint_href, submission,
										   version, old_version )
			self._validate_assignment_containers( new_question.get( 'ntiid' ),
												  assignment_ntiids )

		# Add/remove assignment part
		new_parts = (old_part, new_part)
		res = self.testapp.put_json( assignment_href, {'parts': new_parts})
		res = res.json_body
		qset2 = res.get( 'parts' )[1].get( 'question_set' )
		qset_ntiid2 = qset2.get( "NTIID" )
		question_ntiid2 = qset2.get( 'questions' )[0].get( 'NTIID' )
		version, old_version = _check_version( version )
		q_sub2 = QuestionSubmission(questionId=question_ntiid2,
								    parts=(0,))
		qs_submission2 = QuestionSetSubmission(questionSetId=qset_ntiid2,
											   questions=(q_sub2,))
		submission = AssignmentSubmission(assignmentId=assignment_ntiid,
										  parts=(qs_submission, qs_submission2))
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		new_parts = (old_part,)
		self.testapp.put_json( assignment_href, {'parts': new_parts})
		version, old_version = _check_version( version )
		submission.parts = (qs_submission,)
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		# Edit questions (parts)
		qset = self.testapp.get( qset_href )
		qset = qset.json_body
		questions = qset.get( 'questions' )
		choices = ['one', 'two', 'three', 'four']
		multiple_choice = questions[0]
		multiple_choice_href = multiple_choice.get( 'href' )
		multiple_answer = questions[1]
		multiple_answer_href = multiple_answer.get( 'href' )
		matching = questions[2]
		matching_href = matching.get( 'href' )

		# Multiple choice/answer choice length/reorder changes.
		multiple_choice['parts'][0]['choices'] = choices
		self.testapp.put_json( multiple_choice_href, multiple_choice )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		multiple_choice['parts'][0]['choices'] = tuple(reversed( choices ))
		self.testapp.put_json( multiple_choice_href, multiple_choice )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		multiple_answer['parts'][0]['choices'] = choices
		self.testapp.put_json( multiple_answer_href, multiple_answer )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		multiple_answer['parts'][0]['choices'] = tuple(reversed( choices ))
		self.testapp.put_json( multiple_answer_href, multiple_answer )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		# Add/remove question part
		old_part = multiple_choice['parts'][0]
		new_part = dict(old_part)
		new_part.pop( 'NTIID', None )
		new_part.pop( 'ntiid', None )
		new_parts = (old_part, new_part)
		multiple_choice['parts'] = new_parts
		self.testapp.put_json( multiple_choice_href, multiple_choice )
		version, old_version = _check_version( version )
		old_sub_parts = question_submissions[0].parts
		question_submissions[0].parts = old_sub_parts + ('0',)
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )
		question_submissions[0].parts = old_sub_parts

		new_parts = (old_part,)
		multiple_choice['parts'] = new_parts
		self.testapp.put_json( multiple_choice_href, multiple_choice )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		# Matching value/label length/reorder changes.
		labels = list(choices)
		matching['parts'][0]['labels'] = labels
		matching['parts'][0]['values'] = labels
		matching['parts'][0]['solutions'][0]['value'] = {'0':0,'1':1,'2':2,'3':3}
		self.testapp.put_json( matching_href, matching )
		version, old_version = _check_version( version )
		question_submissions[2].parts = ({'0':0,'1':1,'2':2,'3':3},)
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		matching['parts'][0]['labels'] = tuple(reversed( choices ))
		matching['parts'][0]['values'] = tuple(reversed( choices ))
		self.testapp.put_json( matching_href, matching )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		# Move a question
		move_json = self._get_move_json( question_ntiid, qset_ntiid, 0 )
		self.testapp.post_json( qset_move_href, move_json )
		version, old_version = _check_version( version )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   version, old_version )

		# Test randomization (order is important).
		rel_list = (VIEW_RANDOMIZE, VIEW_RANDOMIZE_PARTS,
					VIEW_UNRANDOMIZE, VIEW_UNRANDOMIZE_PARTS)
		for rel in rel_list:
			new_qset = self.testapp.get( qset_href )
			new_qset = new_qset.json_body
			random_link = self.require_link_href_with_rel(new_qset, rel)
			self.testapp.post( random_link )
			version, old_version = _check_version( version )
			# XXX: Same submission works? (not autograded.)
			self._test_version_submission( assignment_submit_href, savepoint_href, submission,
									   	   version, old_version )

		# Test version does not change
		# Content changes do not affect version
		self.testapp.put_json( assignment_href, {'content': 'new content'} )
		_check_version( version, changed=False )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission, version )

		self.testapp.put_json( qset_href, {'title': 'new title'} )
		_check_version( version, changed=False )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission, version )

		for question in questions:
			self.testapp.put_json( question.get( 'href' ),
								   {'content': 'blehbleh' })
			_check_version( version, changed=False )
			self._test_version_submission( assignment_submit_href, savepoint_href, submission, version )

		# Altering choice/labels/values/solutions does not affect version
		choices = list(reversed( choices ))
		choices[0] = 'fixed typo'
		multiple_choice['parts'][0]['choices'] = choices
		multiple_choice['parts'][0]['solutions'][0]['value'] = 1
		self.testapp.put_json( multiple_choice_href, multiple_choice )
		_check_version( version, changed=False )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission, version )

		multiple_answer['parts'][0]['choices'] = choices
		multiple_answer['parts'][0]['solutions'][0]['value'] = [0,1]
		self.testapp.put_json( multiple_answer_href, multiple_answer )
		_check_version( version, changed=False )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission, version )

		labels = list(choices)
		matching['parts'][0]['labels'] = labels
		matching['parts'][0]['values'] = labels
		matching['parts'][0]['solutions'][0]['value'] = {'0':1,'1':0,'2':2,'3':3}
		self.testapp.put_json( matching_href, matching )
		_check_version( version, changed=False )
		self._test_version_submission( assignment_submit_href, savepoint_href, submission, version )

	@time_monotonically_increases
	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_structural_links(self):
		"""
		Validate assignment (structural) links change when students submit.
		"""
		# Create base assessment object, enroll student, and set up vars for test.
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment()
#		question_set_source = self._load_questionset()
		res = self.testapp.post_json(href, assignment, status=201)
		res = res.json_body
		assignment_href = res.get( 'href' )
		assignment_ntiid = res.get('ntiid')
		assignment_ntiids = (assignment_ntiid,)
		assert_that( res.get( 'version' ), none() )
		old_part = res.get( 'parts' )[0]
		qset = old_part.get( 'question_set' )
		qset_ntiid = qset.get( 'NTIID' )
#		qset_href = qset.get( 'href' )
		question_ntiid = qset.get( 'questions' )[0].get( 'ntiid' )
#		qset_move_href = self.require_link_href_with_rel(qset, VIEW_ASSESSMENT_MOVE)
#		qset_contents_href = self.require_link_href_with_rel(qset, VIEW_QUESTION_SET_CONTENTS)
		self._validate_assignment_containers( qset_ntiid, assignment_ntiids )
		enrolled_student = 'test_student'
		student_environ = self._create_and_enroll( enrolled_student )
#		restricted_structural_status = 422

		# Student has no such links

		# Create submission
		upload_submission = QUploadedFile(data=b'1234',
										  contentType=b'image/gif',
										  filename='foo.pdf')
		q_sub = QuestionSubmission(questionId=question_ntiid,
								   parts=(upload_submission,))

		qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
											  questions=(q_sub,))
		submission = AssignmentSubmission(assignmentId=assignment_ntiid,
										  parts=(qs_submission,))

		# Validate edit state of current assignment.
		self._test_external_state(ntiid=assignment_ntiid,
								  has_submissions=False)

		# Student submits and the edit state changes
		submission = toExternalObject( submission )
		submission['version'] = None
		self.testapp.post_json( assignment_href, submission, extra_environ=student_environ )

		self._test_external_state(ntiid=assignment_ntiid,
								  has_submissions=True)

		# Cannot structurally edit assignment anymore.
		# Cannot add question
		# FIXME: Currently not indexing submissions by question-set and question.
# 		questions = question_set_source.get('questions')
# 		self.testapp.post_json( qset_contents_href, questions[0],
# 								status=restricted_structural_status )
#
# 		# Cannot delete
# 		delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
# 		self.testapp.delete(qset_contents_href + delete_suffix,
# 							status=restricted_structural_status )
#
# 		# Cannot randomize
# 		rel_list = (VIEW_RANDOMIZE, VIEW_RANDOMIZE_PARTS,
# 					VIEW_UNRANDOMIZE, VIEW_UNRANDOMIZE_PARTS)
# 		for rel in rel_list:
# 			random_link = self.require_link_href_with_rel(qset, rel)
# 			self.testapp.post( random_link, status=restricted_structural_status )

		# FIXME: Add same question to another assignment. Should not be able to
		# edit that question.

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
	def test_delete_evaluation(self, mock_vhs):
		course_oid = self._get_course_oid()
		href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
		assignment = self._load_assignment()
		res = self.testapp.post_json(href, assignment, status=201)
		asg_href = res.json_body['href']

		mock_vhs.is_callable().with_args().returns(True)
		res = self.testapp.delete(asg_href, status=422)
		assert_that(res.json_body, has_entry('Links', has_length(1)))
		link_ref = res.json_body['Links'][0]['href']
		self.testapp.delete(link_ref, status=204)

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

		assignment = self._load_assignment()
		res = self.testapp.post_json(href, assignment, status=201)
		asg_href = res.json_body['href']
		ntiid = res.json_body['NTIID']
		data = {'publishBeginning':int(time.time())-10000}
		publish_href = asg_href + '/@@publish'
		res = self.testapp.post_json(publish_href, data, status=200)
		assert_that(res.json_body, has_entry('publishBeginning', is_not(none())))
		# check registered
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			obj = component.queryUtility(IQEvaluation, name=ntiid)
			assert_that(obj.is_published(), is_(True))
			assert_that(obj, has_property('publishBeginning', is_not(none())))

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

		# Inserting questions with blank/empty content is now allowed.
		empty_question = dict( ext_question )
		empty_question.pop( 'content' )
		self.testapp.post_json(contents_href, empty_question)

		empty_question['content'] = ''
		self.testapp.post_json(contents_href, empty_question)

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
