#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_not
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

import shutil
import tempfile

from nti.app.assessment.exporter import AssessmentsExporter
from nti.app.assessment.importer import AssessmentsImporter

from nti.cabinet.filer import DirectoryFiler

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestImporter(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_importer(self):
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            context = find_object_with_ntiid(self.course_ntiid)
            course = ICourseInstance(context)
            tmp_dir = tempfile.mkdtemp(dir="/tmp")
            try:
                filer = DirectoryFiler(tmp_dir)
                exporter = AssessmentsExporter()
                exporter.export(course, filer)
                importer = AssessmentsImporter()
                result = importer.process(course, filer)
                assert_that(result, has_length(184))
            finally:
                shutil.rmtree(tmp_dir, True)
