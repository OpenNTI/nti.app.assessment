#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

import fudge

from hamcrest import is_
from hamcrest import not_none
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import same_instance

import simplejson as json

from zope.component.persistentregistry import PersistentComponents as Components

from persistent import Persistent

from zope import component
from zope import interface

from zope.annotation.interfaces import IAttributeAnnotatable

from nti.app.assessment._question_map import _AssessmentItemBucket
from nti.app.assessment._question_map import QuestionMap as _QuestionMap

from nti.app.assessment._question_map import _get_last_mod_namespace
from nti.app.assessment._question_map import _populate_question_map_from_text
from nti.app.assessment._question_map import _remove_assessment_items_from_oldcontent

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.indexed_data import get_catalog

from nti.contentlibrary.interfaces import IContentUnit

from nti.app.assessment.tests import AssessmentLayerTest

import nti.dataserver.tests.mock_dataserver as mock_dataserver

from nti.dataserver.tests.mock_dataserver import WithMockDSTrans

class QuestionMap(_QuestionMap, dict):
	# For testing, we capture data, emulating
	# previous behaviour.

	def __init__(self):
		_QuestionMap.__init__(self)
		dict.__init__(self)
		self.by_file = dict()

	def _get_by_file(self):
		return self.by_file

	def _store_object(self, k, v):
		self[k] = v

ASSM_ITEMS = {
	'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion':
	{'Class': 'Question',
	 'MimeType': 'application/vnd.nextthought.naquestion',
	 'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion',
	 'content': '<a name="testquestion"></a> Arbitrary content goes here.',
	 'parts': [{'Class': 'SymbolicMathPart',
				'MimeType': 'application/vnd.nextthought.assessment.symbolicmathpart',
				'content': 'Arbitrary content goes here.',
				'explanation': '',
				'hints': [],
				'solutions': [{'Class': 'LatexSymbolicMathSolution',
							   'MimeType': 'application/vnd.nextthought.assessment.latexsymbolicmathsolution',
							   'value': 'Some solution','weight': 1.0}]}]},
	'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.testset':
	{'Class': 'QuestionSet',
	 'MimeType': 'application/vnd.nextthought.naquestionset',
	 'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.testset',
	 'questions': [{'Class': 'Question',
					'MimeType': 'application/vnd.nextthought.naquestion',
					'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion',
					'content': '<a name="testquestion"></a> Arbitrary content goes here.',
					'parts': [{'Class': 'SymbolicMathPart',
							   'MimeType': 'application/vnd.nextthought.assessment.symbolicmathpart',
							   'content': 'Arbitrary content goes here.',
							   'explanation': '',
							   'hints': [],
							   'solutions': [{'Class': 'LatexSymbolicMathSolution',
											  'MimeType': 'application/vnd.nextthought.assessment.latexsymbolicmathsolution',
											  'value': 'Some solution', 'weight': 1.0}]}]}]},
	'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testpoll':
	{'Class': 'Poll',
	 'MimeType': 'application/vnd.nextthought.napoll',
	 'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testpoll',
	 'content': '<a name="testquestion"></a> Arbitrary content goes here.',
	 'parts': [{'Class': 'MultipleChoicePart',
				'MimeType': 'application/vnd.nextthought.assessment.nongradablemultiplechoicepart',
				'content': 'Arbitrary content goes here.',
				"choices": [
					"<a name=\"1e5cd4b70d0ca146665b0073e3512f12\" ></a>\n\n<p class=\"par\" id=\"1e5cd4b70d0ca146665b0073e3512f12\">Distributive </p>",
					"<a name=\"82a183f5bbcaf7607f1e0fb56399a565\" ></a>\n\n<p class=\"par\" id=\"82a183f5bbcaf7607f1e0fb56399a565\">Corrective </p>",
					"<a name=\"d7140284ac92d169d24484726d8a2f10\" ></a>\n\n<p class=\"par\" id=\"d7140284ac92d169d24484726d8a2f10\">Transactional </p>"
				],
				'hints': [] }]},
	'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.survey.testsurvey':
	{'Class': 'Survey',
	 'MimeType': 'application/vnd.nextthought.nasurvey',
	 'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.testsurvey',
	 'questions': [{'Class': 'Poll',
					'MimeType': 'application/vnd.nextthought.napoll',
					'NTIID': 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testpoll',
					'content': '<a name="testquestion">Arbitrary content goes here.',
					'parts': [{'Class': 'MultipleChoicePart',
							   'MimeType': 'application/vnd.nextthought.assessment.nongradablemultiplechoicepart',
							   'content': 'Arbitrary content goes here.',
								"choices": [
										"<a name=\"1e5cd4b70d0ca146665b0073e3512f12\" ></a>\n\n<p class=\"par\" id=\"1e5cd4b70d0ca146665b0073e3512f12\">Distributive </p>",
										"<a name=\"82a183f5bbcaf7607f1e0fb56399a565\" ></a>\n\n<p class=\"par\" id=\"82a183f5bbcaf7607f1e0fb56399a565\">Corrective </p>",
										"<a name=\"d7140284ac92d169d24484726d8a2f10\" ></a>\n\n<p class=\"par\" id=\"d7140284ac92d169d24484726d8a2f10\">Transactional </p>"
								] }]}]}

}

SECTION_ONE = {
	'NTIID': 'tag:nextthought.com,2011-10:testing-HTML-temp.section_one',
#	'filename': 'tag_nextthought_com_2011-10_testing-HTML-temp_section_one.html',
	'href': 'tag_nextthought_com_2011-10_testing-HTML-temp_section_one.html',
	'AssessmentItems': ASSM_ITEMS,
	}

CHAPTER_ONE = {
	'Items': {SECTION_ONE['NTIID']: SECTION_ONE	},
	'NTIID': 'tag:nextthought.com,2011-10:testing-HTML-temp.chapter_one',
	'filename': 'tag_nextthought_com_2011-10_testing-HTML-temp_chapter_one.html',
	'href': 'tag_nextthought_com_2011-10_testing-HTML-temp_chapter_one.html'
	}

ROOT = {
	'Items': { CHAPTER_ONE['NTIID']: CHAPTER_ONE },
	'NTIID': 'tag:nextthought.com,2011-10:testing-HTML-temp.0',
	'filename': 'index.html',
	'href': 'index.html'}

ASSM_JSON_W_SET = {
	'Items': { ROOT['NTIID']: ROOT },
	'href': 'index.html'
	}

ASSM_STRING_W_SET = json.dumps( ASSM_JSON_W_SET, indent='\t' )

ASSESSMENT_STRING_QUESTIONS_IN_FIRST_FILE = """
{
	"Items": {
		"tag:nextthought.com,2011-10:mathcounts-HTML-mathcounts2012.mathcounts_2011_2012": {
			"AssessmentItems": {},
			"Items": {
				"tag:nextthought.com,2011-10:mathcounts-HTML-mathcounts2012.warm_up_1": {
					"AssessmentItems": {
						"tag:nextthought.com,2011-10:mathcounts-NAQ-mathcounts2012.naq.qid.1": """ + json.dumps(ASSM_ITEMS['tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion']) + """

					},
					"NTIID": "tag:nextthought.com,2011-10:mathcounts-HTML-mathcounts2012.warm_up_1",
					"filename": "tag_nextthought_com_2011-10_mathcounts-HTML-mathcounts2012_warm_up_1.html",
					"href": "tag_nextthought_com_2011-10_mathcounts-HTML-mathcounts2012_warm_up_1.html"
				}
			},
			"NTIID": "tag:nextthought.com,2011-10:mathcounts-HTML-mathcounts2012.mathcounts_2011_2012",
			"filename": "index.html",
			"href": "index.html"
		}
	},
	"href": "index.html"
}
"""

@interface.implementer(IContentUnit, IAttributeAnnotatable)
class MockEntry(object):

	def __init__(self):
		self._items = _AssessmentItemBucket()
		self.ntiid = 'tag:nextthought,2011-05:blehblehbleh'

	children = ()

	def make_sibling_key( self, key ):
		return key

	def __conform__(self, iface):
		if iface == IQAssessmentItemContainer:
			return self._items

class PersistentComponents(Components, Persistent):
	pass

from nti.contentlibrary.interfaces import IGlobalContentPackageLibrary

class TestQuestionMap( AssessmentLayerTest ):

	# Provide a fake global library, so that things get registered
	# in the GSM.
	def setUp(self):
		super( TestQuestionMap, self ).setUp()
		component.getGlobalSiteManager().registerUtility(self, IGlobalContentPackageLibrary)

	def tearDown(self):
		super( TestQuestionMap, self ).tearDown()
		component.getGlobalSiteManager().unregisterUtility(self, IGlobalContentPackageLibrary)

	def pathToNTIID(self, ntiid):
		return ()

	def _do_test_create_question_map_captures_set_ntiids(self, index_string=ASSM_STRING_W_SET):
		question_map = QuestionMap()

		mock_content_package = MockEntry()

		# Specify our registry, so we can force index
		_populate_question_map_from_text( question_map, index_string, mock_content_package)

		assm_items = question_map.by_file['tag_nextthought_com_2011-10_testing-HTML-temp_chapter_one.html']

		# Manually add to our content package container
		container = IQAssessmentItemContainer( mock_content_package )
		container.extend( question_map.values() )

		qset = None
		question = None
		assert_that( assm_items, has_length( 4 ) ) # one question, one set
		for item in assm_items:
			if IQuestion.providedBy(item):
				question = item
				assert_that(item, has_property('ntiid', 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion' ) )
				assert_that(item, has_property('__name__', 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion' ) )
			elif IQuestionSet.providedBy(item):
				qset = item
				assert_that( item, has_property('ntiid', 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.testset' ) )
				assert_that( item, has_property('__name__', 'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.testset' ) )

		qset_question = qset.questions[0]
		assert_that( qset_question, is_( question ) )
		assert_that( qset_question, has_property( 'ntiid',     'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion' ) )
		assert_that( qset_question, has_property( '__name__',  'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion' ) )

		assert_that( question_map[qset_question.ntiid], is_( qset_question ) )
		assert_that( question_map[qset_question.ntiid], is_( question) )
		assert_that( question_map[qset.ntiid], is_( qset ) )

		# Registered
		question_set = component.getUtility( IQuestionSet, name=qset.ntiid )
		for question in question_set.questions:
			assert_that( question, is_( same_instance( component.getUtility( IQuestion,
																			 name=question.ntiid ))))

		# Catalogged
		catalog = get_catalog()
		last_mod_namespace = _get_last_mod_namespace( mock_content_package )
		last_modified = catalog.get_last_modified( last_mod_namespace )
		assert_that( last_modified, not_none() )

		# Remove
		_remove_assessment_items_from_oldcontent( mock_content_package )

	@WithMockDSTrans
	@fudge.patch('nti.app.contentlibrary.subscribers.get_site_registry')
	def test_create_question_map_captures_set_ntiids(self, mock_registry):
		registry = PersistentComponents()
		mock_dataserver.current_transaction.add(registry)
		mock_registry.is_callable().returns(registry)
		self._do_test_create_question_map_captures_set_ntiids()

	@WithMockDSTrans
	@fudge.patch('nti.app.contentlibrary.subscribers.get_site_registry')
	def test_create_question_map_nested_level_with_no_filename(self, mock_registry):
		registry = PersistentComponents()
		mock_dataserver.current_transaction.add(registry)
		mock_registry.is_callable().returns(registry)

		section_one = SECTION_ONE.copy()
	#	del section_one['filename']
		chapter_one = CHAPTER_ONE.copy()
		chapter_one['Items'][section_one['NTIID']] = section_one

		root = ROOT.copy()
		root['Items'][chapter_one['NTIID']] = chapter_one

		assm_json = {
			'Items': { root['NTIID']: root },
			'href': 'index.html'
		}

		assm_string = json.dumps( assm_json )

		self._do_test_create_question_map_captures_set_ntiids( assm_string )

	@WithMockDSTrans
	@fudge.patch('nti.app.contentlibrary.subscribers.get_site_registry')
	def test_create_question_map_nested_two_level_with_no_filename(self, mock_registry):
		registry = PersistentComponents()
		mock_dataserver.current_transaction.add(registry)
		mock_registry.is_callable().returns(registry)

		section_one = SECTION_ONE.copy()

		interloper = { 'NTIID': 'foo',
					   'Items': { section_one['NTIID']: section_one } }

		chapter_one = CHAPTER_ONE.copy()
		chapter_one['Items'] = {interloper['NTIID']: interloper}

		root = ROOT.copy()
		root['Items'][chapter_one['NTIID']] = chapter_one

		assm_json = {
			'Items': { root['NTIID']: root },
			'href': 'index.html'
		}

		assm_string = json.dumps( assm_json )

		self._do_test_create_question_map_captures_set_ntiids( assm_string )

	def test_create_from_mathcounts2012_no_Question_section_in_chapter(self):
		index_string = str(ASSESSMENT_STRING_QUESTIONS_IN_FIRST_FILE)

		question_map = QuestionMap()

		_populate_question_map_from_text( question_map, index_string, MockEntry() )

		assert_that( question_map, has_length( 1 ) )

		assm_items = question_map.by_file.get('tag_nextthought_com_2011-10_mathcounts-HTML-mathcounts2012_warm_up_1.html')

		assert_that( assm_items, has_length( 1 ) )
		question = assm_items[0]

		assert_that( question, has_property( '__name__', 'tag:nextthought.com,2011-10:mathcounts-NAQ-mathcounts2012.naq.qid.1' ) )
		assert_that( question, has_property( 'ntiid', 'tag:nextthought.com,2011-10:mathcounts-NAQ-mathcounts2012.naq.qid.1', ) )

	@WithMockDSTrans
	def test_create_with_assignment(self):
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
								{'AssessmentItems': {'tag:nextthought.com,2011-10:testing-NAQ-temp.naq.asg.assignment':
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
		the_text = json.dumps(the_map)

		question_map = QuestionMap()

		entry = MockEntry()
		_populate_question_map_from_text( question_map, the_text, entry )

		# Check that they were canonicalizade
		asg = component.getUtility(IQAssignment, name='tag:nextthought.com,2011-10:testing-NAQ-temp.naq.asg.assignment' )
		qset = component.getUtility(IQuestionSet, name='tag:nextthought.com,2011-10:testing-NAQ-temp.naq.set.set')
		q = component.getUtility(IQuestion, name='tag:nextthought.com,2011-10:testing-NAQ-temp.naq.testquestion')

		assert_that( asg.parts[0].question_set, is_( same_instance( qset )))
		assert_that( qset.questions[0], is_( same_instance(q)) )
