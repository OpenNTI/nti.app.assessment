#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import none
from hamcrest import is_not
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

from zope import component

from nti.recorder.interfaces import IRecordables

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestRecordables(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    @WithSharedApplicationMockDS(users=False, testapp=False)
    def test_recordables(self):
        with mock_dataserver.mock_db_trans(self.ds, site_name='janux.ou.edu'):
            recordables = component.queryUtility(IRecordables, "evaluations")
            assert_that(recordables, is_not(none()))
            assert_that(list(recordables.iter_objects()),
                        has_length(greater_than(300)))
