#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_not
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

from nti.app.assessment.exporter import AssessmentsExporter

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestExporter(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_exporter(self):
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            context = find_object_with_ntiid(self.course_ntiid)
            exporter = AssessmentsExporter()
            ext_obj = exporter.externalize(context)
            assert_that(ext_obj,
                        has_entry('Items',
                                  has_entry('tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.introduction_to_computer_programming',
                                            has_entry('Items',
                                                      has_entry('tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.lec:01.02_LESSON',
                                                                has_entry('Items',
                                                                          has_entry('tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.iclicker_08_26_(not_graded)',
                                                                                    has_entry('AssessmentItems', has_length(1)))))))))
