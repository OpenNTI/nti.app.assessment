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
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_entries
from hamcrest import has_property
from hamcrest import same_instance
does_not = is_not

import os
import time

import simplejson

from zope import component
from zope import interface

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.assessment.evaluations.exporter import EvaluationsExporter
from nti.app.assessment.evaluations.importer import EvaluationsImporter

from nti.app.assessment.evaluations.utils import delete_evaluation

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQTimedAssignment

from nti.contentlibrary.mixins import ContentPackageImporterMixin

from nti.contentlibrary.utils import export_content_package

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.ntiids.ntiids import is_ntiid_of_type
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

    def prepare_json_text(self, data):
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        return data

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_import_export(self):
        source = self.load_resource("evaluation_index.json")
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            importer = EvaluationsImporter()
            importer.process_source(course, source, None)

            # Timed assignment is marker interface
            timed_assignment = component.queryUtility(IQEvaluation,
                                                      name=self.A_NTIID)
            interface.noLongerProvides(timed_assignment, IQTimedAssignment)
            interface.alsoProvides(timed_assignment, IQTimedAssignment)

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

                exporter = EvaluationsExporter()
                result = exporter.export_evaluations(course)
                assert_that(result,
                            has_entries('Items', has_length(3),
                                        'Total', is_(3)))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            evals = IQEvaluations(course)
            registered = component.queryUtility(IQEvaluation,
                                                name=self.A_NTIID)
            delete_evaluation(registered)
            for key in (self.S_NTIID, self.A_NTIID):
                registered = component.queryUtility(IQEvaluation, name=key)
                assert_that(registered, is_(none()))
                assert_that(evals, does_not(has_key(key)))
            assert_that(evals, has_length(1))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            exporter = EvaluationsExporter()
            result = exporter.export_evaluations(course, False,
                                                 str(time.time()))
            assert_that(result,
                        has_entries('Items', has_length(1),
                                    'Total', is_(1)))

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_import_updater(self):
        importer = ContentPackageImporterMixin()
        source = self.load_resource("content_packages.json")
        source = simplejson.loads(self.prepare_json_text(source))
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            items = source['Items']
            added, modified = importer.handle_packages(items)
            assert_that(added, has_length(1))
            assert_that(modified, has_length(0))

            evals = IQEvaluations(added[0])
            assert_that(evals, has_length(1))
            question = next(iter(evals.values()))
            assert_that(question.is_published(), is_(True))

            ntiid = added[0].ntiid
            assert_that(is_ntiid_of_type(ntiid, 'HTML'),
                        is_(True))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            package = find_object_with_ntiid(ntiid)
            ext_obj = export_content_package(package, False, str(time.time()))
            assert_that(ext_obj,
                        has_entry('Evaluations',
                                  has_entry('Items', has_length(1))))
