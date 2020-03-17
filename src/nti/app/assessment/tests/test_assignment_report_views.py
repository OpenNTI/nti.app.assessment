#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
from _ast import Assign
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

import os
import csv
import json

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import has_property
from hamcrest import assert_that
from hamcrest import greater_than

from StringIO import StringIO

from zope import component
from zope import interface

from nti.app.assessment.index import IX_MIMETYPE

from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import TIMED_ASSIGNMENT_MIME_TYPE

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.assessment.submission import QuestionSubmission
from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.assessment.response import QModeledContentResponse

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.externalization.datetime import datetime_from_string

from nti.externalization import to_external_object

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestAssignmentReportViews(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'
    course_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
    course_url = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'

    def _load_json_resource(self, resource="assignment_with_multiple_question_parts.json"):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            result = json.load(fp)
            return result

    def _do_submit(self, assignmentId, questionSetId, questionIds, environ, status=201):
        questions = [QuestionSubmission(questionId=questionIds[0],
                                        parts=[0, 0]),
                     QuestionSubmission(questionId=questionIds[1],
                                        parts=[[0, 1], [0]]),
                     QuestionSubmission(questionId=questionIds[2],
                                        parts=["OK", "Bye"]),
                     QuestionSubmission(questionId=questionIds[3],
                                        parts=[QModeledContentResponse(value=["gogogo"]),
                                               QModeledContentResponse(value=["where should go"])])]

        qs_submission = QuestionSetSubmission(questionSetId=questionSetId,
                                              questions=questions)
        submission = AssignmentSubmission(assignmentId=assignmentId,
                                          parts=(qs_submission,))
        ext_obj = to_external_object(submission)

        # Need to start
        assignment_url = '/dataserver2/Objects/%s' % assignmentId
        assignment_res = self.testapp.get(assignment_url, extra_environ=environ)

        start_href = self.require_link_href_with_rel(assignment_res.json_body, 'Commence')
        res = self.testapp.post(start_href, extra_environ=environ)

        submission_url = self.course_url + '/Assessments/' + assignmentId
        res = self.testapp.post_json(submission_url,
                                     ext_obj,
                                     extra_environ=environ,
                                     status=201)
        return res


    @WithSharedApplicationMockDS(users=True, testapp=True)
    def testAssignmentSubmissionsReportCSV(self):
        editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
        editor_environ['HTTP_ORIGIN'] = b'http://janux.ou.edu'

        url = '%s/CourseEvaluations' % self.course_url
        data = self._load_json_resource()
        result = self.testapp.post_json(url, data, extra_environ=editor_environ).json_body

        assignmentId = result['NTIID']

        questionSetId = result['parts'][0]['question_set']['NTIID']

        questionIds = [x['NTIID'] for x in result['parts'][0]['question_set']['questions']]
        assert_that(questionIds, has_length(4))

        pub_url = '/dataserver2/Objects/%s/@@publish' % assignmentId
        self.testapp.post(pub_url, extra_environ=editor_environ)

        report_url = "/dataserver2/Objects/%s/@@AssignmentSubmissionsReport" % assignmentId
        result = self.testapp.get(report_url, status=200, extra_environ=editor_environ).body
        assert_that(result.splitlines(), has_length(1))
        assert_that(result.split(','), has_length(10))

        self._do_submit(assignmentId, questionSetId, questionIds, editor_environ)

        result = self.testapp.get(report_url, status=200, extra_environ=editor_environ).body
        result = [x for x in csv.reader(StringIO(result), delimiter=str(','))]
        assert_that(result, has_length(2))
        assert_that(result[0], has_length(10))
        assert_that(result[1], has_length(10))
        result = dict(zip(result[0], result[1]))
        assert_that(result["user"], is_('sjohnson@nextthought.com'))
        assert_that(result["submission date (UTC)"], not_none())
        assert_that(result["Where do you live?: City"], is_('Norman'))
        assert_that(result["Where do you live?: State"], is_('OK'))
        assert_that(result["How is the weather?: General"], is_('cloudy, sunny'))
        assert_that(result["How is the weather?: Date"], is_('Tuesday'))
        assert_that(result["How many students in your class?: Number Of Students"], is_('OK'))
        assert_that(result["How many students in your class?: Class"], is_('Bye'))
        assert_that(result["What do you think about your current staying?: You like"], is_('gogogo'))
        assert_that(result["What do you think about your current staying?: You don't like"], is_('where should go'))
