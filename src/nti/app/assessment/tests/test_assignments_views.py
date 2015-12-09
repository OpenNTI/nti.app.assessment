#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
from hamcrest.library.object.hasproperty import has_property
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

from urllib import quote
from itertools import chain

from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.utils import get_course_subinstances

from nti.externalization.datetime import datetime_from_string

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.recorder.interfaces import ITransactionRecordHistory

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.dataserver.tests import mock_dataserver

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

class TestAssignmentViews(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
	course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'
	assignment_id = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_no_context(self):
		url = '/dataserver2/Objects/' + self.assignment_id
		data =  {'available_for_submission_beginning':'2015-11-25T05:00:00Z',
				 'available_for_submission_ending':'2015-11-30T05:00:00Z'}
		self.testapp.put_json(url, data, status=200)
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			ending = datetime_from_string('2015-11-30T05:00:00Z')
			beginning = datetime_from_string('2015-11-25T05:00:00Z')
			
			assert_that(asg, has_property('available_for_submission_ending', is_(ending)))
			assert_that(asg, has_property('available_for_submission_beginning',is_(beginning)))
			
			history  = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)
			subs = get_course_subinstances(course)
			for course in chain((course,), subs):
				policies = IQAssessmentPolicies(course)
				data = policies.get(self.assignment_id)
				assert_that(data, has_entry('locked', is_(True)))
				
				dates = IQAssessmentDateContext(course)
				data = dates.get(self.assignment_id)
				assert_that(data, has_entry('available_for_submission_ending', is_(ending)))
				assert_that(data, has_entry('available_for_submission_beginning',is_(beginning)))
				
	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_with_context(self):
		url = '/dataserver2/Objects/' + self.assignment_id + "?course=%s" % quote(self.course_ntiid)
		data =  {'available_for_submission_beginning':'2015-11-25T05:00:00Z',
				 'available_for_submission_ending':'2015-11-30T05:00:00Z',
				 'title':'ProjectOne'}
		self.testapp.put_json(url, data, status=200)
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			ending = datetime_from_string('2015-11-30T05:00:00Z')
			beginning = datetime_from_string('2015-11-25T05:00:00Z')
			
			assert_that(asg, has_property('title', is_('ProjectOne')))
			assert_that(asg, has_property('available_for_submission_ending', is_not(ending)))
			assert_that(asg, has_property('available_for_submission_beginning',is_not(beginning)))
				
			history  = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)
			
			policies = IQAssessmentPolicies(course)
			data = policies.get(self.assignment_id)
			assert_that(data, has_entry('locked', is_(True)))
				
			dates = IQAssessmentDateContext(course)
			data = dates.get(self.assignment_id)
			assert_that(data, has_entry('available_for_submission_ending', is_(ending)))
			assert_that(data, has_entry('available_for_submission_beginning',is_(beginning)))
