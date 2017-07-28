#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import same_instance
does_not = is_not

import os

from zope import component

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.assessment.evaluations.importer import EvaluationsImporter

from nti.assessment.interfaces import IQEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestImportExport(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    Q_NTIID = u'tag:nextthought.com,2011-10:NTI-NAQ-0082'
    S_NTIID = u'tag:nextthought.com,2011-10:NTI-NAQ-0083'
    A_NTIID = u'tag:nextthought.com,2011-10:NTI-NAQ-0084'

    def load_resource(self, resource):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            return fp.read()

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_import_export(self):
        source = self.load_resource("evaluation_index.json")
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            importer = EvaluationsImporter()
            importer.process_source(course, source, None)

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            evals = IQEvaluations(course)
            assert_that(evals, has_length(3))
            for key in (self.Q_NTIID, self.S_NTIID, self.A_NTIID):
                registered = component.queryUtility(IQEvaluation, name=key)
                assert_that(registered, is_not(none()))
                assert_that(evals, has_key(key))
                assert_that(evals[key], is_(same_instance(registered)))
                assert_that(registered,
                            has_property('__home__'), is_(course))
