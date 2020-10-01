#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904


import base64

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
from hamcrest import is_in
does_not = is_not

import os
import time

import simplejson

from zope import component
from zope import interface

import zlib

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.assessment.evaluations.exporter import EvaluationsExporter
from nti.app.assessment.evaluations.importer import EvaluationsImporter

from nti.app.assessment.evaluations.utils import delete_evaluation

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQTimedAssignment

from nti.assessment.survey import QPoll
from nti.assessment.survey import QSurvey

from nti.contenttypes.courses.interfaces import ICourseExportFiler

from nti.contentlibrary.mixins import ContentPackageImporterMixin

from nti.contentlibrary.utils import export_content_package

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.ntiids.ntiids import is_ntiid_of_type
from nti.ntiids.ntiids import find_object_with_ntiid
from nti.ntiids.ntiids import hash_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class ImportExportTestMixin(object):

    entry_ntiid = None

    IMPORTED_NTIIDS = ()
    NTIIDS_TO_REMOVE = ()
    REMOVED_NTIIDS = ()

    def load_resource(self, resource):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            return fp.read()

    def _post_process_import(self):
        pass

    def _test_import_export(self, resource):
        source = self.load_resource(resource)
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            importer = EvaluationsImporter()
            importer.process_source(course, source, None)

            self._post_process_import()

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            evals = IQEvaluations(course)
            assert_that(evals, has_length(len(self.IMPORTED_NTIIDS)))
            for key in self.IMPORTED_NTIIDS:
                registered = component.queryUtility(IQEvaluation, name=key)
                assert_that(registered, is_not(none()))
                assert_that(evals, has_key(key))
                assert_that(evals[key], is_(same_instance(registered)))
                assert_that(registered,
                            has_property('__home__'), is_(course))

            exporter = EvaluationsExporter()
            result = exporter.export_evaluations(course)
            assert_that(result,
                        has_entries('Items', has_length(len(self.IMPORTED_NTIIDS)),
                                    'Total', is_(len(self.IMPORTED_NTIIDS))))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            evals = IQEvaluations(course)
            for to_remove in self.NTIIDS_TO_REMOVE:
                registered = component.queryUtility(IQEvaluation,
                                                    name=to_remove)
                delete_evaluation(registered)
            for key in self.REMOVED_NTIIDS:
                registered = component.queryUtility(IQEvaluation, name=key)
                assert_that(registered, is_(none()))
                assert_that(evals, does_not(has_key(key)))
            num_evals_after_removal = len(self.IMPORTED_NTIIDS) - len(self.REMOVED_NTIIDS)
            assert_that(evals, has_length(num_evals_after_removal))

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            exporter = EvaluationsExporter()
            result = exporter.export_evaluations(course, False,
                                                 str(time.time()))
            assert_that(result,
                        has_entries('Items', has_length(num_evals_after_removal),
                                    'Total', is_(num_evals_after_removal)))


class TestImportExport(ImportExportTestMixin, ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    Q_NTIID = u'tag:nextthought.com,2011-10:NTI-NAQ-0082'
    S_NTIID = u'tag:nextthought.com,2011-10:NTI-NAQ-0083'
    A_NTIID = u'tag:nextthought.com,2011-10:NTI-NAQ-0084'

    IMPORTED_NTIIDS = (Q_NTIID, S_NTIID, A_NTIID)
    NTIIDS_TO_REMOVE = (A_NTIID,)
    REMOVED_NTIIDS = (S_NTIID, A_NTIID)

    def prepare_json_text(self, data):
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        return data

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_import_export(self):
        self._test_import_export("evaluation_index.json")

    def _post_process_import(self):
        # Timed assignment is marker interface
        timed_assignment = component.queryUtility(IQEvaluation,
                                                  name=self.A_NTIID)
        interface.noLongerProvides(timed_assignment, IQTimedAssignment)
        interface.alsoProvides(timed_assignment, IQTimedAssignment)

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


def encode(content):
    return base64.b64encode(zlib.compress(content))

class TestSurveyImportExport(ImportExportTestMixin, ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    SURVEY_NTIID = u'tag:nextthought.com,2011-10:OU-NAQ-survey_system_4744496732793162703_1679835696'
    POLL_NTIID = u'tag:nextthought.com,2011-10:OU-NAQ-poll_system_4744496732793012824_1679835696'
    VIDEO_NTIID = u'tag:nextthought.com,2011-10:OU-NTIVideo-CS1323_F_2015_Intro_to_Computer_Programming.ntivideo.video_janux_videos'

    IMPORTED_NTIIDS = (POLL_NTIID, SURVEY_NTIID)
    NTIIDS_TO_REMOVE = (SURVEY_NTIID,)
    REMOVED_NTIIDS = (SURVEY_NTIID,)

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_import_export_survey(self):
        self._test_import_export("evaluation_index_survey.json")

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_content_refs(self):
        source = self.load_resource("evaluation_index_survey.json")
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            importer = EvaluationsImporter()
            importer.process_source(course, source, None)

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)
            exporter = EvaluationsExporter()
            salt = b'test'
            filer = ICourseExportFiler(course)
            result = exporter.export_evaluations(course,
                                                 backup=False,
                                                 salt=salt,
                                                 filer=filer)

            expected_poll_ntiid = hash_ntiid(self.POLL_NTIID, salt=salt)
            ext_polls = [eval for eval in result['Items']
                         if eval['MimeType'] == QPoll.mime_type]
            assert_that(ext_polls, has_length(1))
            assert_that(ext_polls[0], has_entries({
                'NTIID': expected_poll_ntiid
            }))

            expected_survey_ntiid = hash_ntiid(self.SURVEY_NTIID, salt=salt)
            expected_vid_ntiid = self.VIDEO_NTIID
            expected_contents = ".. napollref:: %s\n.. ntivideoref:: %s" \
                                % (expected_poll_ntiid, expected_vid_ntiid)
            ext_surveys = [eval for eval in result['Items']
                           if eval['MimeType'] == QSurvey.mime_type]
            assert_that(ext_surveys, has_length(1))
            assert_that(ext_surveys[0], has_entries({
                'NTIID': expected_survey_ntiid,
                'contents': encode(expected_contents)
            }))

            new_source = simplejson.dumps(result)
            importer = EvaluationsImporter()
            importer.process_source(course, new_source, None)

            course_evals = IQEvaluations(course)

            assert_that(expected_poll_ntiid, is_in(course_evals))
            assert_that(expected_survey_ntiid, is_in(course_evals))
            assert_that(course_evals[expected_survey_ntiid].contents,
                        is_(expected_contents))
