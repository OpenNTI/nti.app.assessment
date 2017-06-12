#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

from zope import component

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment

from nti.assessment.submission import AssignmentSubmission

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestCourseViews(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
    course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'
    assignment_id = u'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'

    def add_submission(self, user):
        entry = find_object_with_ntiid(self.course_ntiid)
        course = ICourseInstance(entry)
        history = component.queryMultiAdapter((course, user),
                                              IUsersCourseAssignmentHistory)

        submission = AssignmentSubmission(assignmentId=self.assignment_id)
        pending = QAssignmentSubmissionPendingAssessment(assignmentId=self.assignment_id,
                                                         parts=())
        history.recordSubmission(submission, pending)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_reset_assignment(self):

        with mock_dataserver.mock_db_trans(self.ds):
            self._create_user(u"ichigo")

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            user = self._get_user(u"ichigo")
            self.add_submission(user)

        href = '/dataserver2/Objects/%s?course=%s' % \
               (self.assignment_id, self.course_ntiid)
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body, does_not(has_key('version')))

        href = '/dataserver2/Objects/%s/@@Reset?course=%s' % \
               (self.assignment_id, self.course_ntiid)
        res = self.testapp.post(href, status=200)
        assert_that(res.json_body, has_key('version'))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            user = self._get_user(u"ichigo")
            course = ICourseInstance(find_object_with_ntiid(self.course_ntiid))
            history = component.queryMultiAdapter((course, user),
                                                  IUsersCourseAssignmentHistory)
            assert_that(history, has_length(0))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_reset_user(self):

        with mock_dataserver.mock_db_trans(self.ds):
            self._create_user(u"ichigo")

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            user = self._get_user(u"ichigo")
            self.add_submission(user)

        href = '/dataserver2/Objects/%s/@@UserReset?course=%s' % \
               (self.assignment_id, self.course_ntiid)
        res = self.testapp.post_json(href, {'username': 'ichigo'}, status=200)
        assert_that(res.json_body,
                    has_entry('Items', has_length(greater_than(0))))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            user = self._get_user(u"ichigo")
            course = ICourseInstance(find_object_with_ntiid(self.course_ntiid))
            history = component.queryMultiAdapter((course, user),
                                                  IUsersCourseAssignmentHistory)
            assert_that(history, has_length(0))
