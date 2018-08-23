#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=protected-access,too-many-public-methods

from hamcrest import none
from hamcrest import is_not
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

from zope import component

from nti.contenttypes.completion.interfaces import ICompletables

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestCompletables(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    @WithSharedApplicationMockDS(users=False, testapp=False)
    def test_completables(self):
        with mock_dataserver.mock_db_trans(self.ds, site_name='janux.ou.edu'):
            completables = component.queryUtility(ICompletables, "evaluations")
            assert_that(completables, is_not(none()))
            assert_that(list(completables.iter_objects()),
                        has_length(greater_than(1)))
