#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import assert_that
from hamcrest import has_property
does_not = is_not

from nti.app.assessment.interfaces import IQEvaluations

from nti.contentlibrary.zodb import RenderableContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestAdpaters(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_evaluations(self):
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            evals = IQEvaluations(course, None)
            assert_that(evals, is_not(None))
            assert_that(evals, 
                        has_property('__parent__', is_(course)))

        package = RenderableContentPackage()
        evals = IQEvaluations(package, None)
        assert_that(evals, is_not(None))
        assert_that(evals, 
                    has_property('__parent__', is_(package)))
