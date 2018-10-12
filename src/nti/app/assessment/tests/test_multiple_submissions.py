#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=protected-access,too-many-public-methods

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import raises
from hamcrest import has_key
from hamcrest import calling
from hamcrest import contains
from hamcrest import not_none
from hamcrest import has_item
from hamcrest import has_items
from hamcrest import has_entry
from hamcrest import ends_with
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_entries
from hamcrest import has_property
from hamcrest import contains_string
does_not = is_not

from nti.testing.matchers import is_empty
from nti.testing.matchers import validly_provides

import fudge
import datetime
from six.moves import urllib_parse
from six.moves.urllib_parse import quote
from six.moves.urllib_parse import unquote

from zope import component

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import ConstraintNotSatisfied

from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.adapters import _begin_assessment_for_assignment_submission

from nti.app.assessment.feedback import UsersCourseAssignmentHistoryItemFeedback

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories

from nti.app.assessment.tests import RegisterAssignmentLayer
from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.contentlibrary import LIBRARY_PATH_GET_VIEW

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.contentfragments.interfaces import IPlainTextContentFragment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.users.users import User

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.mimetype.mimetype import nti_mimetype_with_class

from nti.ntiids.ntiids import find_object_with_ntiid


class TestMultipleSubmissions(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
    course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'
    assignment_id = u'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'
    assignment_url = '/dataserver2/Objects/%s?course=%s' % (assignment_id, course_ntiid)
    question_set_id = u"tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.set.qset:Prj_1"

    def _do_submit(self, submission_rel, environ):
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)
        ext_obj['ContainerId'] = u'tag:nextthought.com,2011-10:mathcounts-HTML-MN.2012.0'
        res = self.testapp.post_json(submission_rel,
                                     ext_obj,
                                     extra_environ=environ)
        return res

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_policy_edits(self):
        res = self.testapp.get(self.assignment_url)
        res = res.json_body
        assert_that(res['max_submissions'], is_(1))
        assert_that(res['submission_priority'], is_('most_recent'))

        for bad_value in ('-1', '0', 'a'):
            data =  {'max_submissions': bad_value}
            self.testapp.put_json(self.assignment_url, data, status=422)

        for bad_value in ('-1', '0', 'a', ''):
            data =  {'submission_priority': bad_value}
            self.testapp.put_json(self.assignment_url, data, status=422)

        # Validate 2 submissions max (and we can change submission_priority)
        res = self.testapp.put_json(self.assignment_url, {'max_submissions': 2,
                                                          'submission_priority': 'HIGHEST_GRADE'})
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_priority'], is_('highest_grade'))

        # Enroll user and submit
        with mock_dataserver.mock_db_trans():
            self._create_user('outest55')
        outest_environ = self._make_extra_environ(username='outest55')

        self.testapp.post_json('/dataserver2/CourseAdmin/UserCourseEnroll',
                                     {'ntiid': self.course_ntiid,
                                      'username': 'outest55',
                                      'scope': 'ForCredit'})

        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(0))
        assert_that(res['submission_priority'], is_('highest_grade'))
        submission_rel = self.require_link_href_with_rel(res, 'Submit')
        self.forbid_link_with_rel(res, 'History')
        self.forbid_link_with_rel(res, 'Histories')
        self._do_submit(submission_rel, outest_environ)

        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(1))
        self.require_link_href_with_rel(res, 'Submit')
        history_rel = self.require_link_href_with_rel(res, 'History')
        histories_rel = self.require_link_href_with_rel(res, 'Histories')
        self._do_submit(submission_rel, outest_environ)

        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(2))
        history_rel = self.require_link_href_with_rel(res, 'History')
        histories_rel = self.require_link_href_with_rel(res, 'Histories')
        self.forbid_link_with_rel(res, 'Submit')

        # Reset

