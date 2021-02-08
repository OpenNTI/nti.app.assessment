#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from hamcrest import assert_that
from hamcrest import is_
from hamcrest import none
from hamcrest import not_
from nti.app.assessment.decorators.question import QuestionPartStripper

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.dataserver.tests import mock_dataserver
from zope.component.hooks import getSite

logger = __import__('logging').getLogger(__name__)


class TestSolutionStripping(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = b'http://janux.ou.edu'

    course_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
    course_url = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice'
    qpart_id = u'tag:nextthought.com,2011-10:OU-NAQPart-CLC3403_LawAndJustice.naq.qid.aristotle.1.0'
    base_qpart_url = '/dataserver2/Objects/%s' % (qpart_id,)
    qpart_url = '%s?course=%s' % (base_qpart_url, course_ntiid)

    def _assert_solutions_stripped(self, qpart_url, username):
        json_body = self._fetch_part(qpart_url, username)
        assert_that(json_body['explanation'], is_(none()))
        assert_that(json_body['solutions'], is_(none()))

    def _assert_solutions_present(self, qpart_url, username):
        json_body = self._fetch_part(qpart_url, username)
        assert_that(json_body['explanation'], not_(none()))
        assert_that(json_body['solutions'], not_(none()))

    def _fetch_part(self, qpart_url, username):
        with mock_dataserver.mock_db_trans(site_name="janux.ou.edu"):
            sm = getSite().getSiteManager()
            sm.registerSubscriptionAdapter(QuestionPartStripper)
        try:

            instructor_env = self._make_extra_environ(username=username)
            res = self.testapp.get(qpart_url,
                                   extra_environ=instructor_env)
            json_body = res.json_body
            return json_body
        finally:
            with mock_dataserver.mock_db_trans(site_name="janux.ou.edu"):
                sm = getSite().getSiteManager()
                sm.unregisterSubscriptionAdapter(QuestionPartStripper)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_instructor_no_course(self):
        # Can still get course solely from part, in this case
        self._assert_solutions_present(self.base_qpart_url, u"harp4162")

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_instructor_with_course(self):
        self._assert_solutions_present(self.qpart_url, u"harp4162")

    def _enroll(self, username, course_ntiid):
        admin_environ = self._make_extra_environ(
            username=self.default_username)
        enroll_url = '/dataserver2/CourseAdmin/UserCourseEnroll'
        self.testapp.post_json(enroll_url,
                               {'ntiid': course_ntiid,
                                'username': username},
                               extra_environ=admin_environ)

    @WithSharedApplicationMockDS(users=(u"ralph",), testapp=True)
    def test_non_instructor_no_course(self):
        self._enroll(u"ralph", self.course_ntiid)
        self._assert_solutions_stripped(self.base_qpart_url, u"ralph")

    @WithSharedApplicationMockDS(users=(u"ralph",), testapp=True)
    def test_non_instructor_with_course(self):
        self._enroll(u"ralph", self.course_ntiid)
        self._assert_solutions_stripped(self.qpart_url, u"ralph")
