#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=protected-access,too-many-public-methods

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

from nti.app.assessment import VIEW_RESET_EVALUATION

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.dataserver.tests import mock_dataserver

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
CLASS = StandardExternalFields.CLASS


class TestMultipleSubmissions(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
    course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'
    assignment_id = u'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'
    assignment_url = '%s/Assessments/%s' % (course_url, assignment_id)
    question_set_id = u"tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.set.qset:Prj_1"

    def _do_submit(self, submission_rel, environ, status=201, version=None):
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)
        if version:
            ext_obj['version'] = version
        # Need to start
        assignment_res = self.testapp.get(self.assignment_url, extra_environ=environ)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        res = self.testapp.post(start_href, extra_environ=environ)
        res = res.json_body
        # Validate metadata item state
        meta_item = res.get('CurrentMetadataAttemptItem')
        assert_that(meta_item, not_none())
        assert_that(meta_item, has_entry('MimeType',
                                         'application/vnd.nextthought.assessment.userscourseassignmentattemptmetadataitem'))
        assert_that(meta_item, has_entry('Creator',
                                         'outest55'))
        assert_that(meta_item, has_entry('Duration', none()))
        assert_that(meta_item, has_entry('SubmitTime', none()))
        assert_that(meta_item, does_not(has_item('Seed')))
        assert_that(meta_item, does_not(has_item('HistoryItem')))
        self.require_link_href_with_rel(meta_item, 'Assignment')
        self.forbid_link_with_rel(meta_item, 'HistoryItem')

        res = self.testapp.post_json(submission_rel,
                                     ext_obj,
                                     extra_environ=environ,
                                     status=status)
        return res

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_multiple_submissions(self):
        res = self.testapp.get(self.assignment_url)
        res = res.json_body
        assert_that(res['max_submissions'], is_(1))
        assert_that(res['submission_priority'], is_('highest_grade'))

        for bad_value in ('-2', '0', 'a'):
            data =  {'max_submissions': bad_value}
            self.testapp.put_json(self.assignment_url, data, status=422)

        for bad_value in ('-2', '0', 'a', ''):
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
        instructor_environ = self._make_extra_environ(username='tryt3968')

        record = self.testapp.post_json('/dataserver2/CourseAdmin/UserCourseEnroll',
                                       {'ntiid': self.course_ntiid,
                                        'username': 'outest55',
                                        'scope': 'ForCredit'})
        user_history_href = self.require_link_href_with_rel(record.json_body, 'AssignmentHistory')

        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(0))
        assert_that(res['submission_priority'], is_('highest_grade'))
        submission_rel = self.require_link_href_with_rel(res, 'Submit')
        self.forbid_link_with_rel(res, 'History')
        self.forbid_link_with_rel(res, 'Histories')
        self._do_submit(submission_rel, outest_environ)

        # First submission
        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(1))
        # XXX: Submit rel API is probably obsolete
        self.require_link_href_with_rel(res, 'Submit')

        history_rel = self.require_link_href_with_rel(res, 'History')
        histories_rel = self.require_link_href_with_rel(res, 'Histories')
        res = self.testapp.get(history_rel, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res[CLASS], is_('UsersCourseAssignmentHistoryItem'))
        assert_that(res['submission_count'], is_(1))
        res = self.testapp.get(histories_rel, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res[CLASS], is_('UsersCourseAssignmentHistoryItemContainer'))
        assert_that(res.get('Creator'), is_('outest55'))
        assert_that(res[ITEMS], has_length(1))
        self.forbid_link_with_rel(res, VIEW_RESET_EVALUATION)

        history_item = res[ITEMS][0]
        meta_item1 = history_item.get('MetadataAttemptItem')
        assert_that(meta_item1, not_none())
        assert_that(meta_item1, has_entry('StartTime', not_none()))
        assert_that(meta_item1, has_entry('Duration', not_none()))
        assert_that(meta_item1, has_entry('SubmitTime', not_none()))
        self.require_link_href_with_rel(meta_item1, 'Assignment')
        self.require_link_href_with_rel(meta_item1, 'HistoryItem')

        # Second submission
        self._do_submit(submission_rel, outest_environ)
        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(2))

        history_rel = self.require_link_href_with_rel(res, 'History')
        histories_rel = self.require_link_href_with_rel(res, 'Histories')
        self.forbid_link_with_rel(res, 'Submit')
        res = self.testapp.get(history_rel, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res[CLASS], is_('UsersCourseAssignmentHistoryItem'))
        assert_that(res['submission_count'], is_(2))
        res = self.testapp.get(histories_rel, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res[CLASS], is_('UsersCourseAssignmentHistoryItemContainer'))
        assert_that(res[ITEMS], has_length(2))
        meta_ntiids = {x['MetadataAttemptItem']['NTIID'] for x in res[ITEMS]}
        assert_that(meta_ntiids, has_length(2))
        assert_that(meta_ntiids, has_item(meta_item1['NTIID']))

        # Another submission fails, no commence rel
        assignment_res = self.testapp.get(self.assignment_url,
                                          extra_environ=outest_environ)
        self.forbid_link_with_rel(assignment_res.json_body, 'Commence')

        # Reset
        user_history = self.testapp.get(user_history_href, extra_environ=instructor_environ)
        user_history = user_history.json_body
        reset_url = self.require_link_href_with_rel(user_history[ITEMS][self.assignment_id], VIEW_RESET_EVALUATION)
        self.testapp.post(reset_url, extra_environ=instructor_environ)
        res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
        res = res.json_body
        assert_that(res['max_submissions'], is_(2))
        assert_that(res['submission_count'], is_(0))
        submission_rel = self.require_link_href_with_rel(res, 'Submit')
        self._do_submit(submission_rel, outest_environ)

        # Unlimited submissions
        self.testapp.post(reset_url, extra_environ=instructor_environ)
        res = self.testapp.put_json(self.assignment_url, {'max_submissions': -1,
                                                          'submission_priority': 'HIGHEST_GRADE'})
        res = res.json_body
        assert_that(res['max_submissions'], is_(-1))
        assert_that(res['unlimited_submissions'], is_(True))
        assert_that(res['submission_priority'], is_('highest_grade'))

        for submission_index in range(10):
            self._do_submit(submission_rel, outest_environ)
            res = self.testapp.get(self.assignment_url, extra_environ=outest_environ)
            res = res.json_body
            assert_that(res['max_submissions'], is_(-1))
            assert_that(res['submission_count'], is_(submission_index + 1))
