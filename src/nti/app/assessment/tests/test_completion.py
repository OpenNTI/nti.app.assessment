#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_items
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import greater_than_or_equal_to
does_not = is_not

from itertools import chain

from zope import component

from nti.app.contenttypes.completion import COMPLETION_POLICY_VIEW_NAME
from nti.app.contenttypes.completion import COMPLETION_REQUIRED_VIEW_NAME
from nti.app.contenttypes.completion import COMPLETION_NOT_REQUIRED_VIEW_NAME

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE

from nti.contenttypes.completion.interfaces import IProgress
from nti.contenttypes.completion.interfaces import ICompletableItemProvider
from nti.contenttypes.completion.interfaces import IRequiredCompletableItemProvider
from nti.contenttypes.completion.interfaces import ICompletableItemDefaultRequiredPolicy

from nti.contenttypes.completion.policies import CompletableItemAggregateCompletionPolicy

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.users import User

from nti.ntiids.ntiids import find_object_with_ntiid


class TestCompletion(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
    course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'

    def _set_completion_policy(self):
        aggregate_mimetype = CompletableItemAggregateCompletionPolicy.mime_type
        full_data = {u'MimeType': aggregate_mimetype}
        course_res = self.testapp.get(self.course_url).json_body
        policy_url = self.require_link_href_with_rel(course_res,
                                                     COMPLETION_POLICY_VIEW_NAME)
        return self.testapp.put_json(policy_url, full_data).json_body

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_assignments(self):
        """
        Test required state on assignments.
        """
        href = self.course_url + '/@@AssignmentSummaryByOutlineNode'
        policy_res = self._set_completion_policy()
        res = self.testapp.get(href).json_body
        container = res['Items'].values()
        for assignment in chain(*container):
            assert_that(assignment[u'CompletionDefaultState'], is_(False))
            assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
            assert_that(assignment[u'CompletionRequired'], is_(False))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            course = find_object_with_ntiid(self.course_ntiid)
            course = ICourseInstance(course)
            default_required = ICompletableItemDefaultRequiredPolicy(course)
            assert_that(default_required.mime_types, has_length(0))
            # pylint: disable=no-member
            default_required.mime_types.add(ASSIGNMENT_MIME_TYPE)

            user = User.get_user('sjohnson@nextthought.com')
            providers = component.subscribers((course,),
                                              ICompletableItemProvider)
            providers = tuple(providers)
            assert_that(providers, has_length(greater_than_or_equal_to(1)))
            possible_items = set()
            for provider in providers:
                possible_items.update(provider.iter_items(user))
            assert_that(possible_items, has_length(greater_than_or_equal_to(33)))

        res = self.testapp.get(href).json_body
        container = res['Items'].values()
        for assignment in chain(*container):
            if assignment['MimeType'] == ASSIGNMENT_MIME_TYPE:
                assert_that(assignment[u'CompletionDefaultState'], is_(True))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
                assert_that(assignment[u'CompletionRequired'], is_(True))
            else:
                assert_that(assignment[u'CompletionDefaultState'], is_(False))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
                assert_that(assignment[u'CompletionRequired'], is_(False))

        assignment_ntiid = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'

        required_url = self.require_link_href_with_rel(policy_res,
                                                       COMPLETION_REQUIRED_VIEW_NAME)
        not_required_url = self.require_link_href_with_rel(policy_res,
                                                       COMPLETION_NOT_REQUIRED_VIEW_NAME)
        # Mark an assignment optional
        self.testapp.put_json(not_required_url, {u'ntiid': assignment_ntiid})

        res = self.testapp.get(href).json_body
        container = res['Items'].values()
        for assignment in chain(*container):
            if assignment['ntiid'] == assignment_ntiid:
                assert_that(assignment[u'CompletionDefaultState'], is_(True))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(False))
                assert_that(assignment[u'CompletionRequired'], is_(False))
            elif assignment['MimeType'] == ASSIGNMENT_MIME_TYPE:
                assert_that(assignment[u'CompletionDefaultState'], is_(True))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
                assert_that(assignment[u'CompletionRequired'], is_(True))
            else:
                assert_that(assignment[u'CompletionDefaultState'], is_(False))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
                assert_that(assignment[u'CompletionRequired'], is_(False))

        # Back to required
        self.testapp.put_json(required_url, {u'ntiid': assignment_ntiid})
        res = self.testapp.get(href).json_body
        container = res['Items'].values()
        for assignment in chain(*container):
            if assignment['ntiid'] == assignment_ntiid:
                assert_that(assignment[u'CompletionDefaultState'], is_(True))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(False))
                assert_that(assignment[u'CompletionRequired'], is_(True))
            elif assignment['MimeType'] == ASSIGNMENT_MIME_TYPE:
                assert_that(assignment[u'CompletionDefaultState'], is_(True))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
                assert_that(assignment[u'CompletionRequired'], is_(True))
            else:
                assert_that(assignment[u'CompletionDefaultState'], is_(False))
                assert_that(assignment[u'IsCompletionDefaultState'], is_(True))
                assert_that(assignment[u'CompletionRequired'], is_(False))

        # Completable item provider
        self.testapp.put_json(not_required_url, {u'ntiid': assignment_ntiid})
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            user = User.get_user('sjohnson@nextthought.com')
            course = find_object_with_ntiid(self.course_ntiid)
            course = ICourseInstance(course)
            providers = component.subscribers((course,),
                                              IRequiredCompletableItemProvider)
            providers = tuple(providers)
            assert_that(providers, has_length(greater_than_or_equal_to(1)))
            items = set()
            for provider in providers:
                items.update(provider.iter_items(user))
            assert_that(items, has_length(greater_than_or_equal_to(43)))
            assert_that(items, has_items(has_property('mime_type',
                                                      ASSIGNMENT_MIME_TYPE),
                                         does_not(
                                            has_property('ntiid', assignment_ntiid))))
            progress = component.queryMultiAdapter((user,course), IProgress)
            assert_that(progress.AbsoluteProgress, is_(0))
            assert_that(progress.MaxPossibleProgress, is_(43))
            assert_that(progress.HasProgress, is_(False))
            assert_that(progress.LastModified, none())
