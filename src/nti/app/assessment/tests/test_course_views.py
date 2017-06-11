#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


class TestCourseViews(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
    course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_assessment_items(self):
        href = self.course_url + '/@@AssessmentItems'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))

        href = self.course_url + '/@@AssessmentItems?byOutline=True'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_assignments(self):
        href = self.course_url + '/@@Assignments'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_inquiries(self):
        href = self.course_url + '/@@Inquiries'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_lock_unlock_all_assignments(self):
        href = self.course_url + '/@@LockAllAssignments'
        res = self.testapp.post(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))
        count = res.json_body['Total']

        href = self.course_url + '/@@GetLockAssignments'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))
        assert_that(res.json_body,
                    has_entry('Total', is_(count)))

        href = self.course_url + '/@@UnlockAllAssignments'
        res = self.testapp.post(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', greater_than(0)))

        href = self.course_url + '/@@GetLockedAssignments'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body,
                    has_entry('Items', has_length(0)))
