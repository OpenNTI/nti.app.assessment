#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import assert_that
from hamcrest import has_property
does_not = is_not

from nti.app.assessment.interfaces import IQEvaluations

from nti.contentlibrary.zodb import RenderableContentPackage

from nti.contenttypes.courses.courses import CourseInstance

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestAdpaters(ApplicationLayerTest):

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_evaluations(self):
        with mock_dataserver.mock_db_trans(self.ds) as conn:
            course = CourseInstance()
            conn.add(course)
            evals = IQEvaluations(course, None)
            assert_that(evals, is_not(none()))
            assert_that(evals, 
                        has_property('__parent__', is_(course)))

        package = RenderableContentPackage()
        evals = IQEvaluations(package, None)
        assert_that(evals, is_not(none()))
        assert_that(evals, 
                    has_property('__parent__', is_(package)))
