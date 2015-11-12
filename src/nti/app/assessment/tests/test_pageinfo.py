#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_entries
from hamcrest import greater_than
does_not = is_not

from nti.app.testing.application_webtest import ApplicationLayerTest
from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.app.assessment.tests import InstructedCourseApplicationTestLayer

class TestPageInfo(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = str('http://janux.ou.edu')
	
	page_ntiid = 'tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.project_10_(100_points)'
	question_ntiid = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Lab_10'

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_fetch_pageinfo_with_questions(self):
		page_ntiid = self.page_ntiid
		
		accept_type = b'application/vnd.nextthought.pageinfo+json'
		__traceback_info__ = accept_type
		res = self.fetch_by_ntiid(page_ntiid,
								   headers={b"Accept": accept_type})
		assert_that(res.status_int, is_(200))
		assert_that(res.last_modified, is_(not_none()))

		assert_that(res.content_type, is_('application/vnd.nextthought.pageinfo+json'))
		assert_that(res.json_body, has_entry('MimeType', 'application/vnd.nextthought.pageinfo'))
		assert_that(res.json_body,
					has_entry('AssessmentItems', has_length(1)))
		assert_that(res.json_body,
					has_entry('AssessmentItems',
							  has_item(has_entry('NTIID', self.question_ntiid))))
		assert_that(res.json_body['AssessmentItems'],
					has_item(has_entry('containerId',
									   'tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.learning_objectives.6')))
		assert_that(res.json_body, has_entry('Last Modified', greater_than(0)))

		assert_that(res.json_body,
					has_entries('ContentPackageNTIID', 'tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.introduction_to_computer_programming',
								'NTIID', u'tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.project_10_(100_points)',
 								'Title', u'Project 10 (100 points)'))
