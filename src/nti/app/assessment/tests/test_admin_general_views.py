#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import assert_that
from hamcrest import has_entries
from hamcrest import greater_than_or_equal_to
does_not = is_not

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


class TestAdminGeneralViews(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    pkg_ntiid = u'tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.introduction_to_computer_programming'

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_rebuild_eval_catalog(self):
        res = self.testapp.post('/dataserver2/@@RebuildEvaluationCatalog',
                                 status=200)
        assert_that(res.json_body,
                    has_entries('Total', is_(greater_than_or_equal_to(0)),
                                'ItemCount', is_(greater_than_or_equal_to(0))))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_rebuild_submission_catalog(self):
        res = self.testapp.post('/dataserver2/@@RebuildSubmissionCatalog',
                                 status=200)
        assert_that(res.json_body,
                    has_entries('Total', is_(greater_than_or_equal_to(0)),
                                'ItemCount', is_(greater_than_or_equal_to(0))))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_unregister_regiser_items(self):
        href = '/dataserver2/Objects/%s/@@UnregisterAssessmentItems' % self.pkg_ntiid
        res = self.testapp.post(href, status=200)
        assert_that(res.json_body,
                    has_entries('Total', is_(214),
                                'ItemCount', is_(214)))

        href = '/dataserver2/Objects/%s/@@RegisterAssessmentItems' % self.pkg_ntiid
        res = self.testapp.post(href, status=200)
        assert_that(res.json_body,
                    has_entries('Total', is_(214),
                                'ItemCount', is_(214)))
