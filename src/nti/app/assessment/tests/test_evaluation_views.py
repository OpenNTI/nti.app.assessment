#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904
import contextlib

from datetime import datetime

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import contains
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import greater_than
from hamcrest import has_property
from hamcrest import contains_inanyorder
does_not = is_not

from nti.testing.time import time_monotonically_increases

import os
import json
import time
import fudge
import copy

from six.moves.urllib_parse import quote

from zope import component

from zope.intid.interfaces import IIntIds

from zope.lifecycleevent import IObjectModifiedEvent

from nti.app.assessment import get_evaluation_catalog

from nti.app.assessment import VIEW_DELETE
from nti.app.assessment import VIEW_MOVE_PART
from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_INSERT_PART
from nti.app.assessment import VIEW_REMOVE_PART
from nti.app.assessment import VIEW_IS_NON_PUBLIC
from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_MOVE_PART_OPTION
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS
from nti.app.assessment import VIEW_INSERT_PART_OPTION
from nti.app.assessment import VIEW_REMOVE_PART_OPTION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS
from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.common.evaluations import is_discussion_assignment_non_public
from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.evaluations.exporter import EvaluationsExporter

from nti.app.assessment.index import IX_NTIID
from nti.app.assessment.index import IX_MIMETYPE

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH

from nti.appserver.context_providers import get_hierarchy_context
from nti.appserver.context_providers import get_joinable_contexts
from nti.appserver.context_providers import get_top_level_contexts
from nti.appserver.context_providers import get_top_level_contexts_for_user

from nti.assessment import IQPoll

from nti.assessment.interfaces import QUESTION_MIME_TYPE
from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE
from nti.assessment.interfaces import QUESTION_BANK_MIME_TYPE
from nti.assessment.interfaces import DISCUSSION_ASSIGNMENT_MIME_TYPE

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQuestionSet

from nti.assessment.parts import QFilePart

from nti.assessment.randomized.interfaces import IQuestionBank

from nti.assessment.response import QUploadedFile

from nti.assessment.submission import QuestionSubmission
from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.assessment.survey import QPollSubmission
from nti.assessment.survey import QSurveySubmission

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.users.users import User

from nti.externalization import to_external_object

from nti.externalization.externalization import toExternalObject

from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid

from nti.recorder.interfaces import ITransactionRecordHistory

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver

NTIID = StandardExternalFields.NTIID
ITEMS = StandardExternalFields.ITEMS
COURSE_URL = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'


class TestEvaluationViews(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    def _load_json_resource(self, resource):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            result = json.load(fp)
            return result

    def _load_questionset(self):
        return self._load_json_resource("questionset.json")

    def _load_assignment(self):
        return self._load_json_resource("assignment.json")

    def _load_assignment_no_solutions(self):
        return self._load_json_resource("assignment_no_solutions.json")

    def _load_survey(self):
        return self._load_json_resource("survey-freeresponse.json")

    def _load_poll(self):
        return self._load_json_resource("poll1.json")

    def _get_course_oid(self, entry_ntiid=None):
        entry_ntiid = entry_ntiid if entry_ntiid else self.entry_ntiid
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(entry_ntiid)
            course = ICourseInstance(entry)
            return to_external_ntiid_oid(course)

    def _test_assignments(self, assessment_ntiid, assignment_ntiids=()):
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = find_object_with_ntiid(assessment_ntiid)
            assignments = get_containers_for_evaluation_object(obj)
            found_ntiids = tuple(x.ntiid for x in assignments)
            assert_that(found_ntiids, is_(assignment_ntiids))

    def _test_external_state(self, ext_obj=None, ntiid=None,
                             has_savepoints=False, has_submissions=False,
                             randomized=False, randomized_parts=False,
                             *unused_args, **unused_kwargs):
        """
        Test the external state of the given ext_obj or ntiid. We test that
        status changes based on submissions and other user interaction.
        """
        # 'available' not used to limit editing.
        if not ext_obj:
            href = '/dataserver2/Objects/%s' % ntiid
            ext_obj = self.testapp.get(href).json_body

        limited = has_savepoints or has_submissions
        assert_that(ext_obj.get('LimitedEditingCapabilities'), is_(limited))
        assert_that(ext_obj.get('LimitedEditingCapabilitiesSavepoints'),
                    is_(has_savepoints))
        assert_that(ext_obj.get('LimitedEditingCapabilitiesSubmissions'),
                    is_(has_submissions))

        # We always have schema and edit rels.
        for rel in ('schema', 'edit'):
            self.require_link_href_with_rel(ext_obj, rel)

        # We drive these links based on the submission/savepoint status.
        submission_rel_checks = []
        ext_mime = ext_obj.get('MimeType')
        if ext_mime == QUESTION_MIME_TYPE:
            submission_rel_checks.extend((VIEW_MOVE_PART,
                                          VIEW_INSERT_PART,
                                          VIEW_REMOVE_PART,
                                          VIEW_MOVE_PART_OPTION,
                                          VIEW_INSERT_PART_OPTION,
                                          VIEW_REMOVE_PART_OPTION))
        elif ext_mime == ASSIGNMENT_MIME_TYPE:
            submission_rel_checks.extend((VIEW_MOVE_PART,
                                          VIEW_INSERT_PART,
                                          VIEW_REMOVE_PART,
                                          VIEW_IS_NON_PUBLIC,
                                          'date-edit-start',
                                          'maximum-time-allowed'))
            self.require_link_href_with_rel(ext_obj, 'date-edit-end')
        elif ext_mime == QUESTION_SET_MIME_TYPE:
            # Randomize is context sensitive and tested elsewhere.
            submission_rel_checks.extend((VIEW_QUESTION_SET_CONTENTS,
                                          VIEW_ASSESSMENT_MOVE))
            assert_that(ext_obj.get('Randomized'), is_(randomized))
            assert_that(ext_obj.get('RandomizedPartsType'),
                        is_(randomized_parts))

        link_to_check = self.forbid_link_with_rel if limited else self.require_link_href_with_rel
        for rel in submission_rel_checks:
            link_to_check(ext_obj, rel)

        # If assignment, check auto_grade ref matches auto_grade status of
        # parts.
        if ext_mime == ASSIGNMENT_MIME_TYPE:
            for part in ext_obj.get('parts') or ():
                qset = part.get('question_set')
                for question in qset.get('questions') or ():
                    for part in question.get('parts') or ():
                        auto_gradable = part.get('AutoGradable')
                        assert_that(auto_gradable, not_none())
                        if not auto_gradable:
                            assert_that(part.get('MimeType'),
                                        is_(QFilePart.mime_type))

    def _test_qset_ext_state(self, qset, creator, assignment_ntiid, **kwargs):
        self._test_assignments(qset.get(NTIID),
                               assignment_ntiids=(assignment_ntiid,))
        self._test_external_state(qset, **kwargs)
        assert_that(qset.get("Creator"), is_(creator))
        assert_that(qset.get(NTIID), not_none())
        for question in qset.get('questions'):
            question_ntiid = question.get(NTIID)
            assert_that(question.get("Creator"), is_(creator))
            assert_that(question_ntiid, not_none())
            self._test_assignments(question_ntiid,
                                   assignment_ntiids=(assignment_ntiid,))
            self._test_external_state(question, **kwargs)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_qset_with_question_ntiids(self):
        """
        Post to an assignment with a question set with ntiids only.
        """
        course_oid = self._get_course_oid()
        evaluation_href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        qset = self._load_questionset()
        res = self.testapp.post_json(evaluation_href, qset, status=201)
        res = res.json_body
        qset_ntiid = res.get('NTIID')
        question_count = len(res.get('questions'))
        question_ntiid = res.get('questions')[0].get('NTIID')

        # Create an assignment
        assignment = self._load_assignment()
        res = self.testapp.post_json(evaluation_href, assignment, status=201)
        res = res.json_body
        assignment_href = res.get('href')
        old_parts = res.get('parts')
        question_set = old_parts[0]['question_set']
        question_set.pop(NTIID)
        question_set.pop('ntiid')
        question_set['questions'] = (question_ntiid,)

        # Now empty the parts
        res = self.testapp.put_json(assignment_href, {'parts': []})
        res = res.json_body
        assert_that(res.get('parts'), has_length(0))

        # Insert with question_ntiid in questions
        res = self.testapp.put_json(assignment_href, {'parts': old_parts})
        res = res.json_body
        parts = res.get('parts')
        assert_that(parts, has_length(1))
        qset = parts[0].get('question_set')
        assert_that(qset, not_none())
        questions = qset.get('questions')
        assert_that(questions, has_length(1))
        assert_that(questions[0].get(NTIID), is_(question_ntiid))

        # Empty parts and post question set ntiid
        res = self.testapp.put_json(assignment_href, {'parts': []})
        res = res.json_body
        assert_that(res.get('parts'), has_length(0))

        old_parts[0]['question_set'] = qset_ntiid
        res = self.testapp.put_json(assignment_href, {'parts': old_parts})
        res = res.json_body
        parts = res.get('parts')
        assert_that(parts, has_length(1))
        qset = parts[0].get('question_set')
        assert_that(qset, not_none())
        questions = qset.get('questions')
        assert_that(questions, has_length(question_count))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_creating_assessments(self):
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        qset = self._load_questionset()
        creator = u'sjohnson@nextthought.com'

        # post
        posted = []
        for question in qset['questions']:
            res = self.testapp.post_json(href, question, status=201)
            assert_that(res.json_body.get('Creator'), not_none())
            assert_that(res.json_body, has_entry(NTIID, not_none()))
            self._test_external_state(res.json_body)
            posted.append(res.json_body)
        # get
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body, has_entry('ItemCount', greater_than(1)))
        # put
        hrefs = []
        for question in posted:
            url = question.pop('href')
            self.testapp.put_json(url, question, status=200)
            hrefs.append(url)

        # Edit question
        self.testapp.put_json(url, {'content': 'blehcontent'})

        # Post (unpublished) assignment
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        self._test_external_state(res)
        assignment_ntiid = res.get(NTIID)
        assignment_href = res['href']
        assert_that(assignment_ntiid, not_none())
        hrefs.append(assignment_href)
        assert_that(res.get("Creator"), is_(creator))
        for part in res.get('parts'):
            part_qset = part.get('question_set')
            qset_href = part_qset.get('href')
            assert_that(qset_href, not_none())
            self._test_qset_ext_state(part_qset, creator,
                                      assignment_ntiid, available=False)

        # Now publish; items are available since they are in a published
        # assignment.
        self.testapp.post('%s/@@publish' % assignment_href)
        part_qset = self.testapp.get(qset_href)
        part_qset = part_qset.json_body
        self._test_qset_ext_state(part_qset, creator,
                                  assignment_ntiid, available=True)

        # Post qset
        res = self.testapp.post_json(href, qset, status=201)
        res = res.json_body
        assert_that(res, has_entry(NTIID, not_none()))
        hrefs.append(res['href'])
        qset_ntiid = res.get(NTIID)
        assert_that(res.get("Creator"), is_(creator))
        assert_that(qset_ntiid, not_none())
        self._test_assignments(qset_ntiid)
        self._test_external_state(res)
        for question in res.get('questions'):
            question_ntiid = question.get(NTIID)
            assert_that(question.get("Creator"), is_(creator))
            assert_that(question_ntiid, not_none())
            self._test_assignments(question_ntiid)
            self._test_external_state(question)

        # delete first question
        self.testapp.delete(hrefs[0], status=204)
        # items as questions
        qset = self._load_questionset()
        qset.pop('questions', None)
        questions = qset['Items'] = [p['ntiid'] for p in posted[1:]]
        res = self.testapp.post_json(href, qset, status=201)
        assert_that(res.json_body,
                    has_entry('questions', has_length(len(questions))))
        qset_href = res.json_body['href']
        qset_ntiid = res.json_body['NTIID']
        assert_that(qset_ntiid, not_none())

        # No submit assignment, without parts/qset.
        assignment = self._load_assignment()
        assignment.pop('parts', None)
        self.testapp.post_json(href, assignment, status=201)

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            exporter = EvaluationsExporter()
            exported = exporter.externalize(entry)
            assert_that(exported, has_entry('Items', has_length(13)))

        copy_ref = qset_href + '/@@Copy'
        res = self.testapp.post(copy_ref, status=201)
        assert_that(res.json_body, has_entry('NTIID', is_not(qset_ntiid)))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_editing_assignments(self):
        editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        # Make assignment empty, without questions
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_url = res.get('href')
        qset = res.get('parts')[0].get('question_set')
        qset_contents_href = self.require_link_href_with_rel(qset,
                                                             VIEW_QUESTION_SET_CONTENTS)
        question_ntiid = qset.get('questions')[0].get('ntiid')
        delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
        self.testapp.delete(qset_contents_href + delete_suffix)

        # Test auto_assess (starts out False)
        data = {'auto_assess': True}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('parts')[0].get('auto_grade'), is_(True))

        data = {'AutoAssess': False}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('parts')[0].get('auto_grade'), is_(False))

        # Test editing auto_grade/points. total_points can be set without
        # auto_grade.
        data = {'total_points': 100}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(False))
        assert_that(res.get('total_points'), is_(100))

        data = {'auto_grade': False, 'total_points': 5}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(False))
        assert_that(res.get('total_points'), is_(5))

        data = {'auto_grade': 'true', 'total_points': 500}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(True))
        assert_that(res.get('total_points'), is_(500))

        data = {'auto_grade': 'false', 'total_points': 2.5}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(False))
        assert_that(res.get('total_points'), is_(2.5))

        # Empty points
        data = {'total_points': None}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(False))
        assert_that(res.get('total_points'), none())

        # Errors
        data = {'auto_grade': 'what', 'total_points': 2.5}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ,
                                    status=422)
        assert_that(res.json_body.get('field'), is_('auto_grade'))

        data = {'auto_grade': 10, 'total_points': 2.5}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ,
                                    status=422)
        assert_that(res.json_body.get('field'), is_('auto_grade'))

        data = {'auto_grade': 'True', 'total_points': -1}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ,
                                    status=422)
        assert_that(res.json_body.get('field'), is_('total_points'))

        data = {'auto_grade': 'True', 'total_points': 'bleh'}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ,
                                    status=422)
        assert_that(res.json_body.get('field'), is_('total_points'))

        # Auto-grade challenges
        # auto-grade without points, 422.
        data = {'auto_grade': 'True'}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ, status=422)

        # Auto_grade with points
        data = {'auto_grade': 'True', 'total_points': 10}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(True))
        assert_that(res.get('total_points'), is_(10))

        # Setting points to empty with auto_grade on; challenge.
        data = {'total_points': None}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ, status=409)
        confirm_link = self.require_link_href_with_rel(
            res.json_body, 'confirm')
        # Now override and disable
        self.testapp.put_json(confirm_link, data, extra_environ=editor_environ)

        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(False))
        assert_that(res.get('total_points'), none())

        # Validated auto-grading state.
        data = {'auto_grade': 'True', 'total_points': 10}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)

        # Add gradable question when auto-grade enabled.
        qset_source = self._load_questionset()
        gradable_question = qset_source.get('questions')[0]
        self.testapp.post_json(qset_contents_href, gradable_question)

        # File part non-gradable cannot be added.
        file_question = {'Class': 'Question',
                         'MimeType': 'application/vnd.nextthought.naquestion',
                         'content': '<a name="testquestion"></a> Arbitrary content goes here.',
                         'parts': [{'Class': 'FilePart',
                                    'MimeType': 'application/vnd.nextthought.assessment.filepart',
                                    'allowed_extensions': [],
                                    'allowed_mime_types': ['application/pdf'],
                                    'content': 'Arbitrary content goes here.',
                                    'explanation': u'',
                                    'hints': [],
                                    'max_file_size': None,
                                    'solutions': []}]}
        res = self.testapp.post_json(qset_contents_href + '/index/0',
                                     file_question, status=409)
        res = res.json_body
        force_link = self.require_link_href_with_rel(res, 'confirm')
        assert_that(res.get('code'), is_('UngradableInAutoGradeAssignment'))
        # Auto_grade still enabled
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(True))

        # Until they are forced; auto_grade is then disabled.
        self.testapp.post_json(force_link, file_question)
        res = self.testapp.get(assignment_url,
                               extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('auto_grade'), is_(False))

        # Turn off auto-grade and add file part
        data = {'auto_grade': 'False'}
        self.testapp.put_json(assignment_url,
                              data, extra_environ=editor_environ)
        self.testapp.post_json(qset_contents_href, file_question)

        # Now enabling auto-grading fails.
        data = {'auto_grade': 'True'}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ,
                                    status=422)
        assert_that(res.json_body.get('code'),
                    is_('UngradableInAutoGradeAssignment'))

        # Toggle is_non_public
        # Without ForCredit students, this will 409 until we force it
        data = {'is_non_public': 'True'}
        res = self.testapp.put_json(assignment_url,
                                    data, extra_environ=editor_environ,
                                    status=409)
        confirm_href = self.require_link_href_with_rel(res.json_body, 'confirm')
        self.testapp.put_json(confirm_href,
                              data, extra_environ=editor_environ)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.app.assessment.evaluations.subscribers.has_submissions')
    def test_create_timed(self, mock_has_submissions):
        """
        Test creating timed assignment.
        """
        mock_has_submissions.is_callable().returns(False)
        course_oid = self._get_course_oid()
        assignment = self._load_assignment()
        old_parts = assignment['parts']
        assignment['parts'] = []
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_href = res.get('href')

        # Make timed
        max_time = 300
        data = {'maximum_time_allowed': max_time}
        self.testapp.put_json(assignment_href, data)

        data = {'parts': old_parts}
        res = self.testapp.put_json(assignment_href, data)
        res = res.json_body
        assert_that(res.get('parts'), has_length(1))

        # Can edit timed title even if submissions
        mock_has_submissions.is_callable().returns(True)
        self.testapp.put_json(assignment_href, {'title': 'new_title'})

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_created_discussion_assignment(self):
        """
        Test creating discussion assignments.
        """
        course_oid = self._get_course_oid()
        assignment = self._load_assignment()
        old_parts = assignment['parts']
        course_href = '/dataserver2/Objects/%s' % course_oid
        forum_href = '%s/Discussions/In_Class_Discussions/contents' % course_href
        forum_res = self.testapp.get(forum_href)
        forum_res = forum_res.json_body
        # ForCredit discussion
        discussion_ntiid = forum_res[ITEMS][0].get(NTIID)
        assignment['discussion_ntiid'] = discussion_ntiid
        assignment['parts'] = []
        assignment['Class'] = 'DiscussionAssignment'
        assignment['MimeType'] = DISCUSSION_ASSIGNMENT_MIME_TYPE

        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        ntiid = res['ntiid']
        assert_that(ntiid, not_none())
        assert_that(res.get('CanInsertQuestions'), is_(False))
        assert_that(res.get('is_non_public'), is_(True))
        self.forbid_link_with_rel(res, VIEW_IS_NON_PUBLIC)
        assignment_href = res.get('href')

        # Non public discussion assignment
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            assignment_obj = find_object_with_ntiid(ntiid)
            non_public = is_discussion_assignment_non_public(assignment_obj)
            assert_that(non_public, is_(True))

        self.require_link_href_with_rel(res, VIEW_DELETE)
        for part_rel in (VIEW_MOVE_PART, VIEW_REMOVE_PART, VIEW_INSERT_PART):
            self.forbid_link_with_rel(res, part_rel)

        # Must exist
        assignment['discussion_ntiid'] = 'tag:nextthought.com,2011-10:dne'
        self.testapp.post_json(href, assignment, status=422)

        # Must point to topic
        assignment['discussion_ntiid'] = course_oid
        self.testapp.post_json(href, assignment, status=422)

        # Cannot transform type
        data = {'maximum_time_allowed': 300}
        self.testapp.put_json(assignment_href, data, status=422)

        # Cannot add parts
        data = {'parts': old_parts}
        res = self.testapp.put_json(assignment_href, data, status=422)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_question_bank_toggle(self):
        """
        Test toggling a question set to/from question bank.
        """
        course_oid = self._get_course_oid()
        assignment = self._load_assignment()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_ntiid = res.get(NTIID)
        original_res = res.get('parts')[0].get('question_set')
        qset_ntiid = original_res.get('ntiid')
        qset_href = '/dataserver2/Objects/%s' % qset_ntiid
        unchanging_keys = ('Creator', 'CreatedTime', 'title', 'ntiid')

        self._test_transaction_history(qset_ntiid, count=0)

        # Invalid draw
        data = {'draw': -1}
        self.testapp.put_json(qset_href, data, status=422)

        # Convert to question bank
        draw_count = 3
        data = {'draw': 3}
        res = self.testapp.put_json(qset_href, data)

        res = self.testapp.get(qset_href)
        res = res.json_body
        # Class is always question set.
        assert_that(res.get('Class'), is_('QuestionSet'))
        assert_that(res.get('MimeType'), is_(QUESTION_BANK_MIME_TYPE))
        assert_that(res.get('draw'), is_(draw_count))
        assert_that(res.get('ranges'), has_length(0))
        for key in unchanging_keys:
            assert_that(res.get(key), is_(original_res.get(key)), key)

        def _get_question_banks():
            cat = get_evaluation_catalog()
            bank_objs = tuple(cat.apply(
                {
					IX_MIMETYPE: {'any_of': (QUESTION_BANK_MIME_TYPE,)}
				}))
            return bank_objs

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            qset = find_object_with_ntiid(qset_ntiid)
            obj = component.queryUtility(IQuestionBank, name=qset_ntiid)
            assert_that(obj, not_none())
            assert_that(obj.ntiid, is_(qset_ntiid))
            assert_that(obj, is_(qset))
            intids = component.getUtility(IIntIds)
            obj_id = intids.getId(obj)
            # Validate index
            catalog = get_evaluation_catalog()
            rs = catalog.get(IX_NTIID).values_to_documents.get(qset_ntiid)
            assert_that(rs, contains(obj_id))

            question_banks = _get_question_banks()
            assert_that(question_banks, has_item(obj_id))
            # Validate assignment ref.
            assignment = find_object_with_ntiid(assignment_ntiid)
            assignment_qset = assignment.parts[0].question_set
            assert_that(intids.getId(assignment_qset), is_(obj_id))

        # TODO: No create record?
        self._test_transaction_history(qset_ntiid, count=1)

        # Convert back to question set
        data = {'draw': None}
        self.testapp.put_json(qset_href, data)
        res = self.testapp.get(qset_href)
        res = res.json_body
        assert_that(res.get('Class'), is_('QuestionSet'))
        assert_that(res.get('MimeType'), is_(QUESTION_SET_MIME_TYPE))
        assert_that(res.get('draw'), none())
        assert_that(res.get('ranges'), none())
        for key in unchanging_keys:
            assert_that(res.get(key), is_(original_res.get(key)), key)

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            qset = find_object_with_ntiid(qset_ntiid)
            obj = component.queryUtility(IQuestionBank, name=qset_ntiid)
            assert_that(obj, none())
            obj = component.queryUtility(IQuestionSet, name=qset_ntiid)
            assert_that(obj, not_none())
            assert_that(obj.ntiid, is_(qset_ntiid))
            assert_that(obj, is_(qset))
            intids = component.getUtility(IIntIds)
            obj_id = intids.getId(obj)

            # Validate index
            catalog = get_evaluation_catalog()
            rs = catalog.get(IX_NTIID).values_to_documents.get(qset_ntiid)
            assert_that(rs, contains(obj_id))

            question_banks = _get_question_banks()
            assert_that(question_banks, does_not(has_item(obj_id)))

            # Validate assignment ref.
            assignment = find_object_with_ntiid(assignment_ntiid)
            assignment_qset = assignment.parts[0].question_set
            assert_that(intids.getId(assignment_qset), is_(obj_id))
        self._test_transaction_history(qset_ntiid, count=2)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_part_validation(self):
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        qset = res.get('parts')[0].get('question_set')
        qset_contents_href = self.require_link_href_with_rel(qset,
                                                             VIEW_QUESTION_SET_CONTENTS)

        question_set = self._load_questionset()
        questions = question_set.get('questions')
        multiple_choice = questions[0]
        multiple_answer = questions[1]
        matching = questions[2]

        # Multiple choice
        dupes = ['1', '2', '3', '1']
        # Clients may have html wrapped dupes
        html_dupes = ['1', '2',
                      '<a data-id="data-id111"></a>Choice 1',
                      '<a data-id="data-id222"></a>Choice 1']
        # Empties are now allowed in choices/labels/values.
        empties = ['test', 'empty', '', 'try']
        dupe_index = 3
        html_dupe_index = 3
        empty_choice_status = 201

        # Multiple choice duplicates
        multiple_choice['parts'][0]['choices'] = html_dupes
        res = self.testapp.post_json(qset_contents_href,
                                     multiple_choice, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('choices'))
        assert_that(res.get('index'), contains(html_dupe_index))

        multiple_choice['parts'][0]['choices'] = dupes
        res = self.testapp.post_json(qset_contents_href,
                                     multiple_choice, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('choices'))
        assert_that(res.get('index'), contains(dupe_index))

        # Multiple choice empty
        multiple_choice['parts'][0]['choices'] = empties
        res = self.testapp.post_json(qset_contents_href, multiple_choice,
                                     status=empty_choice_status)

        # Multiple answer duplicates
        multiple_answer['parts'][0]['choices'] = dupes
        res = self.testapp.post_json(qset_contents_href,
                                     multiple_answer, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('choices'))
        assert_that(res.get('index'), contains(dupe_index))

        # Multiple answer empty
        multiple_answer['parts'][0]['choices'] = empties
        res = self.testapp.post_json(qset_contents_href, multiple_answer,
                                     status=empty_choice_status)

        # Matching duplicate labels
        old_labels = matching['parts'][0]['labels']
        matching['parts'][0]['labels'] = dupes
        res = self.testapp.post_json(qset_contents_href, matching, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('labels'))
        assert_that(res.get('index'), contains(dupe_index))

        # Matching empty labels
        matching['parts'][0]['labels'] = empties + ['11', '12', '13']
        res = self.testapp.post_json(qset_contents_href, matching,
                                     status=empty_choice_status)

        # Matching duplicate values
        matching['parts'][0]['labels'] = old_labels
        matching['parts'][0]['values'] = dupes
        res = self.testapp.post_json(qset_contents_href, matching, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('values'))
        assert_that(res.get('index'), contains(dupe_index))

        # Matching empty values
        matching['parts'][0]['values'] = empties + ['11', '12', '13']
        res = self.testapp.post_json(qset_contents_href, matching,
                                     status=empty_choice_status)

        # Matching multiple duplicates
        matching['parts'][0]['values'] = ['1', '2', '1', '3', '3', '1']
        res = self.testapp.post_json(qset_contents_href, matching, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('values'))
        assert_that(res.get('index'), contains(2, 4, 5))

        # Matching unequal count
        matching['parts'][0]['values'] = dupes[:-1]
        res = self.testapp.post_json(qset_contents_href, matching, status=422)
        res = res.json_body
        assert_that(res.get('field'), is_('values'))
        assert_that(res.get('code'), is_('InvalidLabelsValues'))

    def _validate_assignment_containers(self, obj_ntiid, assignment_ntiids=()):
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = find_object_with_ntiid(obj_ntiid)
            assignments = get_containers_for_evaluation_object(obj)
            found_ntiids = [x.ntiid for x in assignments or ()]
            assert_that(found_ntiids, contains_inanyorder(*assignment_ntiids))

    def _test_version_submission(self, submit_href, savepoint_href, submission,
                                 new_version, old_version=None):
        """
        Test submissions with versions.
        """
        # We do this by doing the PracticeSubmission with instructor, which does not
        # persist. We savepoint with instructor even though the link is not
        # available.
        submission = toExternalObject(submission)
        hrefs = (submit_href, savepoint_href)
        if old_version:
            # All 409s if we post no version or old version on an assignment
            # with version.
            submission.pop('version', None)
            for href in hrefs:
                self.testapp.post_json(href, submission, status=409)
            submission['version'] = None
            for href in hrefs:
                self.testapp.post_json(href, submission, status=409)
            submission['version'] = old_version
            for href in hrefs:
                self.testapp.post_json(href, submission, status=409)
        if not new_version:
            # Assignment has no version, post with nothing is ok too.
            submission.pop('version', None)
            for href in hrefs:
                self.testapp.post_json(href, submission)
        submission['version'] = new_version
        # XXX: We are not testing assessed results...
        self.testapp.post_json(submit_href, submission)
        res = self.testapp.post_json(savepoint_href, submission)
        res = res.json_body
        # Cleanup savepoint for future tests
        self.testapp.delete(res.get('href'))

    def _create_and_enroll(self, username, entry_ntiid=None):
        entry_ntiid = entry_ntiid if entry_ntiid else self.entry_ntiid
        with mock_dataserver.mock_db_trans(self.ds):
            self._create_user(username=username)
        environ = self._make_extra_environ(username=username)
        admin_environ = self._make_extra_environ(
            username=self.default_username)
        enroll_url = '/dataserver2/CourseAdmin/UserCourseEnroll'
        self.testapp.post_json(enroll_url,
                               {'ntiid': entry_ntiid,
                                'username': username},
                               extra_environ=admin_environ)
        return environ

    @time_monotonically_increases
    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.app.assessment.views.savepoint_views.get_current_metadata_attempt_item')
    def test_assignment_versioning(self, fudge_meta):
        """
        Validate various edits bump an assignment's version and
        may not be allowed if there are savepoints or submissions.

        XXX: AssignmentParts set below are not auto_grade...
        """
        # Must have meta attempt when dealing with timed assignments
        fudge_meta.is_callable().returns(True)
        # Create base assessment object, enroll student, and set up vars for
        # test.
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        question_set_source = self._load_questionset()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_href = res.get('href')
        assignment_submit_href = self.require_link_href_with_rel(res,
                                                                 ASSESSMENT_PRACTICE_SUBMISSION)
        publish_href = self.require_link_href_with_rel(res, VIEW_PUBLISH)
        assignment_ntiid = res.get('ntiid')
        assignment_ntiids = (assignment_ntiid,)
        savepoint_href = '/dataserver2/Objects/%s/AssignmentSavepoints/sjohnson@nextthought.com/%s/Savepoint' % \
            (course_oid, assignment_ntiid)
        assert_that(res.get('version'), none())
        old_part = res.get('parts')[0]
        qset = old_part.get('question_set')
        # Must have at least one question...
        new_part = {"Class": "AssignmentPart",
                    "MimeType": "application/vnd.nextthought.assessment.assignmentpart",
                                "auto_grade": False,
                                "content": "",
                                "question_set": {
                                    "Class": "QuestionSet",
                                    "MimeType": "application/vnd.nextthought.naquestionset",
                                    "questions": [question_set_source.get('questions')[0], ]
                                }
                    }
        qset_ntiid = qset.get('NTIID')
        qset_href = qset.get('href')
        question_ntiid = qset.get('questions')[0].get('ntiid')
        qset_move_href = self.require_link_href_with_rel(qset,
                                                         VIEW_ASSESSMENT_MOVE)
        qset_contents_href = self.require_link_href_with_rel(qset,
                                                             VIEW_QUESTION_SET_CONTENTS)
        self._validate_assignment_containers(qset_ntiid, assignment_ntiids)
        self.testapp.post(publish_href)

        # Get submission ready
        upload_submission = QUploadedFile(data=b'1234',
                                          contentType=b'image/gif',
                                          filename=u'foo.pdf')
        q_sub = QuestionSubmission(questionId=question_ntiid,
                                   parts=(upload_submission,))

        qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
                                              questions=(q_sub,))
        submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                          parts=(qs_submission,))
        self._test_version_submission(
            assignment_submit_href, savepoint_href, submission, None)

        def _check_version(old_version=None, changed=True):
            """
            Validate assignment version has changed and return the new version.
            """
            to_check = is_not if changed else is_
            assignment_res = self.testapp.get(assignment_href)
            new_version = assignment_res.json_body.get('version')
            assert_that(new_version, to_check(old_version))
            assert_that(new_version, not_none())
            return new_version, old_version

        # Delete a question
        delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
        self.testapp.delete(qset_contents_href + delete_suffix)
        version, _ = _check_version()
        # No assignments for ntiid
        self._validate_assignment_containers(question_ntiid)

        # Add three questions
        question_submissions = []
        questions = question_set_source.get('questions')
        # XXX: Skip file upload question
        for question in questions[:-1]:
            new_question = self.testapp.post_json(qset_contents_href, question)
            new_question = new_question.json_body
            question_mime = new_question.get('MimeType')
            solution = ('0',)
            if 'matchingpart' in question_mime:
                solution = ({'0': 0, '1': 1, '2': 2, '3': 3,
                             '4': 4, '5': 5, '6': 6},)
            elif 'filepart' in question_mime:
                solution = (upload_submission,)
            new_submission = QuestionSubmission(questionId=new_question.get('NTIID'),
                                                parts=solution)
            question_submissions.append(new_submission)
            version, old_version = _check_version(version)
            qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
                                                  questions=question_submissions)
            submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                              parts=(qs_submission,))
            self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                          version, old_version)
            self._validate_assignment_containers(new_question.get('ntiid'),
                                                 assignment_ntiids)

        # Add assignment part
        new_parts = (old_part, new_part)
        res = self.testapp.put_json(assignment_href, {'parts': new_parts})
        res = res.json_body
        new_part = res.get('parts')[1]
        qset2 = new_part.get('question_set')
        qset_ntiid2 = qset2.get("NTIID")
        question_ntiid2 = qset2.get('questions')[0].get('NTIID')
        version, old_version = _check_version(version)
        q_sub2 = QuestionSubmission(questionId=question_ntiid2,
                                    parts=(0,))
        qs_submission2 = QuestionSetSubmission(questionSetId=qset_ntiid2,
                                               questions=(q_sub2,))
        submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                          parts=(qs_submission, qs_submission2))
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Re-order assignment parts
        new_parts = (new_part, old_part)
        self.testapp.put_json(assignment_href, {'parts': new_parts})
        version, old_version = _check_version(version)
        submission.parts = (qs_submission2, qs_submission)
        self._test_version_submission(assignment_submit_href, savepoint_href,
                                      submission, version, old_version)

        # Remove assignment part
        new_parts = (old_part,)
        self.testapp.put_json(assignment_href, {'parts': new_parts})
        version, old_version = _check_version(version)
        submission.parts = (qs_submission,)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Edit questions (parts)
        qset = self.testapp.get(qset_href)
        qset = qset.json_body
        questions = qset.get('questions')
        choices = ['one', 'two', 'three', 'four']
        multiple_choice = questions[0]
        multiple_choice_href = multiple_choice.get('href')
        multiple_answer = questions[1]
        multiple_answer_href = multiple_answer.get('href')
        matching = questions[2]
        matching_href = matching.get('href')

        # Multiple choice/answer choice length/reorder changes.
        multiple_choice['parts'][0]['choices'] = choices
        self.testapp.put_json(multiple_choice_href, multiple_choice)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        multiple_choice['parts'][0]['choices'] = tuple(reversed(choices))
        self.testapp.put_json(multiple_choice_href, multiple_choice)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        multiple_answer['parts'][0]['choices'] = choices
        self.testapp.put_json(multiple_answer_href, multiple_answer)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        multiple_answer['parts'][0]['choices'] = tuple(reversed(choices))
        self.testapp.put_json(multiple_answer_href, multiple_answer)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Add question part
        old_part = multiple_choice['parts'][0]
        new_part = dict(old_part)
        new_part.pop('NTIID', None)
        new_part.pop('ntiid', None)
        new_parts = (old_part, new_part)
        multiple_choice['parts'] = new_parts
        res = self.testapp.put_json(multiple_choice_href, multiple_choice)
        res = res.json_body
        new_part = res.get('parts')[1]
        version, old_version = _check_version(version)
        old_sub_parts = question_submissions[0].parts
        question_submissions[0].parts = old_sub_parts + ('0',)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Re-order question parts
        question_submissions[0].parts = ('0',) + old_sub_parts
        new_parts = (new_part, old_part)
        multiple_choice['parts'] = new_parts
        self.testapp.put_json(multiple_choice_href, multiple_choice)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Remove question part
        question_submissions[0].parts = old_sub_parts
        new_parts = (old_part,)
        multiple_choice['parts'] = new_parts
        self.testapp.put_json(multiple_choice_href, multiple_choice)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Matching value/label length/reorder changes.
        labels = list(choices)
        matching['parts'][0]['labels'] = labels
        matching['parts'][0]['values'] = labels
        matching['parts'][0]['solutions'][0]['value'] = {
            '0': 0, '1': 1, '2': 2, '3': 3
        }
        self.testapp.put_json(matching_href, matching)
        version, old_version = _check_version(version)
        question_submissions[2].parts = ({'0': 0, '1': 1, '2': 2, '3': 3},)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        matching['parts'][0]['labels'] = tuple(reversed(choices))
        matching['parts'][0]['values'] = tuple(reversed(choices))
        self.testapp.put_json(matching_href, matching)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Move a question
        move_json = self._get_move_json(question_ntiid, qset_ntiid, 0)
        self.testapp.post_json(qset_move_href, move_json)
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Max time allowed
        self.testapp.put_json(assignment_href, {'maximum_time_allowed': 1000})
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        self.testapp.put_json(assignment_href, {'maximum_time_allowed': None})
        version, old_version = _check_version(version)
        self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                      version, old_version)

        # Test randomization (order is important).
        rel_list = (VIEW_RANDOMIZE, VIEW_RANDOMIZE_PARTS,
                    VIEW_UNRANDOMIZE, VIEW_UNRANDOMIZE_PARTS)
        for rel in rel_list:
            new_qset = self.testapp.get(qset_href)
            new_qset = new_qset.json_body
            random_link = self.require_link_href_with_rel(new_qset, rel)
            self.testapp.post(random_link)
            version, old_version = _check_version(version)
            # XXX: Same submission works? (not autograded.)
            self._test_version_submission(assignment_submit_href, savepoint_href, submission,
                                          version, old_version)

        # Test version does not change
        # Content changes do not affect version
        self.testapp.put_json(assignment_href, {'content': 'new content'})
        _check_version(version, changed=False)
        self._test_version_submission(assignment_submit_href,
                                      savepoint_href, submission, version)

        self.testapp.put_json(qset_href, {'title': 'new title'})
        _check_version(version, changed=False)
        self._test_version_submission(assignment_submit_href,
                                      savepoint_href, submission, version)

        for question in questions:
            self.testapp.put_json(question.get('href'),
                                  {'content': 'blehbleh'})
            _check_version(version, changed=False)
            self._test_version_submission(assignment_submit_href,
                                          savepoint_href, submission, version)

        # Altering choice/labels/values/solutions does not affect version
        choices = list(reversed(choices))
        choices[0] = 'fixed typo'
        multiple_choice['parts'][0]['choices'] = choices
        multiple_choice['parts'][0]['solutions'][0]['value'] = 1
        self.testapp.put_json(multiple_choice_href, multiple_choice)
        _check_version(version, changed=False)
        self._test_version_submission(assignment_submit_href,
                                      savepoint_href, submission, version)

        multiple_answer['parts'][0]['choices'] = choices
        multiple_answer['parts'][0]['solutions'][0]['value'] = [0, 1]
        self.testapp.put_json(multiple_answer_href, multiple_answer)
        _check_version(version, changed=False)
        self._test_version_submission(assignment_submit_href,
                                      savepoint_href, submission, version)

        labels = list(choices)
        matching['parts'][0]['labels'] = labels
        matching['parts'][0]['values'] = labels
        matching['parts'][0]['solutions'][0]['value'] = {
            '0': 1, '1': 0, '2': 2, '3': 3
        }
        self.testapp.put_json(matching_href, matching)
        _check_version(version, changed=False)
        self._test_version_submission(assignment_submit_href, savepoint_href,
                                      submission, version)

    @time_monotonically_increases
    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_structural_links(self):
        """
        Validate assignment (structural) links change when students submit.
        """
        # Create base assessment object (published), enroll student, and set up
        # vars for test.
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        question_set_source = self._load_questionset()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_href = res.get('href')
        assignment_post_href = '%s?ntiid=%s' % (assignment_href, course_oid)
        assignment_ntiid = res.get('ntiid')
        assignment_ntiids = (assignment_ntiid,)
        self.testapp.post('%s/@@publish' % assignment_href)
        assert_that(res.get('version'), none())
        old_part = res.get('parts')[0]
        qset = old_part.get('question_set')
        qset_ntiid = qset.get('NTIID')
        qset_href = qset.get('href')
        question_ntiid = qset.get('questions')[0].get('ntiid')

        self.require_link_href_with_rel(qset, VIEW_ASSESSMENT_MOVE)
        qset_contents_href = self.require_link_href_with_rel(qset,
                                                             VIEW_QUESTION_SET_CONTENTS)
        self._validate_assignment_containers(qset_ntiid, assignment_ntiids)
        enrolled_student = 'test_student'
        student_environ = self._create_and_enroll(enrolled_student)
        restricted_structural_status = 422

        # TODO: Student has no such links
        # TODO: Test move

        # Create submission
        upload_submission = QUploadedFile(data=b'1234',
                                          contentType=b'image/gif',
                                          filename=u'foo.pdf')
        q_sub = QuestionSubmission(questionId=question_ntiid,
                                   parts=(upload_submission,))

        qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
                                              questions=(q_sub,))
        submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                          parts=(qs_submission,))

        # Validate edit state of current assignment.
        self._test_external_state(ntiid=assignment_ntiid,
                                  has_submissions=False)

        # Student submits and the edit state changes
        submission = toExternalObject(submission)
        submission['version'] = None
        assignment_res = self.testapp.get(assignment_href, extra_environ=student_environ)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href, extra_environ=student_environ)
        self.testapp.post_json(assignment_post_href, submission,
                               extra_environ=student_environ)

        self._test_external_state(ntiid=assignment_ntiid,
                                  has_submissions=True)

        # Cannot structurally edit assignment anymore.
        # Cannot add question
        questions = question_set_source.get('questions')
        self.testapp.post_json(qset_contents_href, questions[0],
                               status=restricted_structural_status)

        # Cannot delete question set.
        delete_suffix = self._get_delete_url_suffix(0, question_ntiid)
        self.testapp.delete(qset_contents_href + delete_suffix,
                            status=restricted_structural_status)

        # Cannot randomize or set max_time
        rel_list = (VIEW_RANDOMIZE, VIEW_RANDOMIZE_PARTS,
                    VIEW_UNRANDOMIZE, VIEW_UNRANDOMIZE_PARTS)
        for rel in rel_list:
            random_link = '%s/%s' % (qset_href, rel)
            self.testapp.post(random_link, status=restricted_structural_status)

        # TODO: Add same question to another assignment. Should not be able to
        # edit that question.

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_assignment_no_solutions(self):
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment_no_solutions()
        self.testapp.post_json(href, assignment, status=422)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.app.assessment.evaluations.subscribers.has_submissions',
                 'nti.app.assessment.evaluations.utils.has_submissions')
    def test_change_with_subs(self, mock_ehs, mock_vhs):
        mock_ehs.is_callable().with_args().returns(False)
        mock_vhs.is_callable().with_args().returns(False)

        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        qset = self._load_questionset()
        question = qset['questions'][0]
        res = self.testapp.post_json(href, question, status=201)
        question = res.json_body

        mock_ehs.is_callable().with_args().returns(True)
        mock_vhs.is_callable().with_args().returns(True)

        url = question.pop('href')
        self.testapp.put_json(url, question, status=200)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_delete_containment(self):
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        qset = self._load_questionset()
        res = self.testapp.post_json(href, qset, status=201)
        qset_href = res.json_body['href']
        ntiid = res.json_body['NTIID']
        # cannot delete a contained object
        question = res.json_body['questions'][0]
        href = href + '/%s' % quote(question['NTIID'])
        self.testapp.delete(href, status=422)
        # delete container
        self.testapp.delete(qset_href, status=204)
        # now delete again
        self.testapp.delete(href, status=204)
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = component.queryUtility(IQuestion, name=ntiid)
            assert_that(obj, is_(none()))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.app.assessment.views.deletion_views.has_submissions')
    def test_delete_evaluation(self, mock_vhs):
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        asg_href = res.json_body['href']

        mock_vhs.is_callable().with_args().returns(True)
        res = self.testapp.delete(asg_href, status=409)
        assert_that(res.json_body, has_entry('Links', has_length(1)))
        link_ref = res.json_body['Links'][0]['href']
        self.testapp.delete(link_ref, status=204)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_publish_unpublish(self):
        enrolled_student = 'test_student'
        student_environ = self._create_and_enroll(enrolled_student)
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        qset = self._load_questionset()
        # post question
        question = qset['questions'][0]
        res = self.testapp.post_json(href, question, status=201)
        q_href = res.json_body['href']
        # check not registered
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            ntiid = res.json_body['NTIID']
            obj = component.queryUtility(IQuestion, name=ntiid)
            assert_that(obj.is_published(), is_(False))
        publish_href = q_href + '/@@publish'
        self.testapp.post(publish_href, status=200)
        # check registered
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = component.queryUtility(IQuestion, name=ntiid)
            assert_that(obj.is_published(), is_(True))

        unpublish_href = q_href + '/@@unpublish'

        # try w/o submissions
        self.testapp.post(unpublish_href, status=200)
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = component.queryUtility(IQuestion, name=ntiid)
            assert_that(obj.is_published(), is_(False))

        # Assignment
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_href = res['href']
        assignment_href = '%s?ntiid=%s' % (assignment_href, course_oid)
        assignment_ntiid = res['NTIID']
        publish_href = self.require_link_href_with_rel(res, VIEW_PUBLISH)
        unpublish_href = self.require_link_href_with_rel(res, VIEW_UNPUBLISH)
        data = {'publishBeginning': int(time.time()) - 10000}
        publish_res = self.testapp.post_json(publish_href, data, status=200)
        assert_that(publish_res.json_body,
                    has_entry('publishBeginning', not_none()))
        # Check registered
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = component.queryUtility(IQEvaluation, name=assignment_ntiid)
            assert_that(obj.is_published(), is_(True))
            assert_that(obj, has_property('publishBeginning', not_none()))

        # Savepoints/submissions; no publish links and cannot unpublish.
        upload_submission = QUploadedFile(data=b'1234',
                                          contentType=b'image/gif',
                                          filename=u'foo.pdf')
        qset = res.get('parts')[0].get('question_set')
        qset_ntiid = qset.get('ntiid')
        question_ntiid = qset.get('questions')[0].get('ntiid')
        q_sub = QuestionSubmission(questionId=question_ntiid,
                                   parts=(upload_submission,))
        qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
                                              questions=(q_sub,))
        submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                          parts=(qs_submission,))

        submission = toExternalObject(submission)
        savepoint_href = '/dataserver2/Objects/%s/AssignmentSavepoints/sjohnson@nextthought.com/%s/Savepoint'
        savepoint_href = savepoint_href % (course_oid, assignment_ntiid)
        assignment_res = self.testapp.get(assignment_href)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        savepoint = self.testapp.post_json(savepoint_href, submission)
        assignment = self.testapp.get(assignment_href)
        self.forbid_link_with_rel(assignment.json_body, VIEW_PUBLISH)
        self.forbid_link_with_rel(assignment.json_body, VIEW_UNPUBLISH)
        self.testapp.post(unpublish_href, status=422)

        # Submission
        self.testapp.delete(savepoint.json_body.get('href'))
        assignment_res = self.testapp.get(assignment_href, extra_environ=student_environ)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href, extra_environ=student_environ)
        self.testapp.post_json(assignment_href, submission,
                               extra_environ=student_environ)
        assignment = self.testapp.get(assignment_href)
        self.forbid_link_with_rel(assignment.json_body, VIEW_PUBLISH)
        self.forbid_link_with_rel(assignment.json_body, VIEW_UNPUBLISH)
        self.testapp.post(unpublish_href, status=422)

    def _get_move_json(self, obj_ntiid, new_parent_ntiid, index=None, old_parent_ntiid=None):
        result = {'ObjectNTIID': obj_ntiid,
                  'ParentNTIID': new_parent_ntiid}
        if index is not None:
            result['Index'] = index
        if old_parent_ntiid is not None:
            result['OldParentNTIID'] = old_parent_ntiid
        return result

    def _test_transaction_history(self, ntiid, count=0):
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            obj = find_object_with_ntiid(ntiid)
            assert_that(obj, not_none())
            history = ITransactionRecordHistory(obj)
            record_types = [x.type for x in history.records()]
            assert_that(record_types, has_length(count))

    def _get_question_ntiids(self, ntiid=None, ext_obj=None):
        """
        For the given ntiid or ext_obj (of assignment or question set),
        return all of the underlying question ntiids.
        """
        if not ext_obj:
            res = self.testapp.get('/dataserver2/Objects/%s' % ntiid)
            ext_obj = res.json_body
        if ext_obj.get('Class') != 'QuestionSet':
            ext_obj = ext_obj.get('parts')[0].get('question_set')
        questions = ext_obj.get('questions')
        return [x.get('NTIID') for x in questions]

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_move(self):
        """
        Test moving questions within question sets.
        """
        # Initialize and install qset and one assignments.
        course_oid = self._get_course_oid()
        course = self.testapp.get('/dataserver2/Objects/%s' % course_oid)
        course = course.json_body
        evaluations_href = self.require_link_href_with_rel(course,
                                                           'CourseEvaluations')
        qset = self._load_questionset()
        qset = self.testapp.post_json(evaluations_href, qset, status=201)
        qset_ntiid = qset.json_body.get('NTIID')
        move_href = self.require_link_href_with_rel(qset.json_body,
                                                    VIEW_ASSESSMENT_MOVE)
        qset_question_ntiids = self._get_question_ntiids(ext_obj=qset.json_body)
        assignment = self._load_assignment()
        assignment1 = self.testapp.post_json(evaluations_href,
                                             assignment, status=201)
        assignment1 = assignment1.json_body
        qset2 = assignment1.get('parts')[0].get('question_set')
        qset2_ntiid = qset2.get('NTIID')
        qset2_move_href = self.require_link_href_with_rel(qset2,
                                                          VIEW_ASSESSMENT_MOVE)

        # Move last question to first.
        moved_ntiid = qset_question_ntiids[-1]
        move_json = self._get_move_json(moved_ntiid, qset_ntiid, 0)
        self.testapp.post_json(move_href, move_json)
        new_question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(new_question_ntiids,
                    is_(qset_question_ntiids[-1:] + qset_question_ntiids[:-1]))
        self._test_transaction_history(moved_ntiid, count=1)

        # Move back
        move_json = self._get_move_json(moved_ntiid, qset_ntiid)
        self.testapp.post_json(move_href, move_json)
        new_question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(new_question_ntiids, is_(qset_question_ntiids))
        self._test_transaction_history(moved_ntiid, count=2)

        # Move within a question set invalid.
        dne_ntiid = qset_ntiid + 'xxx'
        move_json = self._get_move_json(moved_ntiid, dne_ntiid, index=1)
        self.testapp.post_json(move_href, move_json, status=422)

        # Ntiid does not exist in qset2.
        move_json = self._get_move_json(moved_ntiid, qset2_ntiid,
                                        index=1, old_parent_ntiid=dne_ntiid)
        self.testapp.post_json(qset2_move_href, move_json, status=422)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_insert_and_replace(self):
        """
        Test inserting/replacing questions in question sets.
        """
        # Initialize and install qset
        course_oid = self._get_course_oid()
        course = self.testapp.get('/dataserver2/Objects/%s' % course_oid)
        course = course.json_body
        evaluations_href = self.require_link_href_with_rel(course,
                                                           'CourseEvaluations')
        qset = self._load_questionset()
        ext_question = qset.get('questions')[0]
        qset = self.testapp.post_json(evaluations_href, qset, status=201)
        qset = qset.json_body
        contents_href = self.require_link_href_with_rel(qset,
                                                        VIEW_QUESTION_SET_CONTENTS)
        qset_ntiid = qset.get('NTIID')
        original_question_ntiids = self._get_question_ntiids(ext_obj=qset)

        # Add a question
        new_question = self.testapp.post_json(evaluations_href,
                                              ext_question, status=201)
        question_ntiid1 = new_question.json_body.get('NTIID')
        new_question = self.testapp.post_json(evaluations_href,
                                              ext_question, status=201)
        question_ntiid2 = new_question.json_body.get('NTIID')

        # Append just ntiid
        self.testapp.post_json(contents_href, {'ntiid': question_ntiid1})
        original_question_ntiids.append(question_ntiid1)
        question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(question_ntiids, is_(original_question_ntiids))

        # Insert/append
        inserted_question = self.testapp.post_json(contents_href, ext_question)
        new_question_ntiid = inserted_question.json_body.get('NTIID')
        original_question_ntiids.append(new_question_ntiid)
        question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(question_ntiids, is_(original_question_ntiids))

        # Prepend
        inserted_question = self.testapp.post_json(contents_href + '/index/0',
                                                   ext_question)
        new_question_ntiid2 = inserted_question.json_body.get('NTIID')
        original_question_ntiids = [new_question_ntiid2] + original_question_ntiids
        question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(question_ntiids, is_(original_question_ntiids))

        # Inserting questions with blank/empty content is allowed.
        empty_question = dict(ext_question)
        empty_question.pop('content')
        self.testapp.post_json(contents_href, empty_question)

        empty_question['content'] = ''
        self.testapp.post_json(contents_href, empty_question)

        # Invalid ntiid
        self.testapp.post_json(contents_href,
                               {'ntiid': question_ntiid1 + 'xxx'},
                               status=422)

        # Replace
        original_question_ntiids = self._get_question_ntiids(qset_ntiid)
        self.testapp.put_json(contents_href + '/index/1',
                              {'ntiid': question_ntiid2})
        original_question_ntiids[1] = question_ntiid2
        question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(question_ntiids, is_(original_question_ntiids))

        # Replace with no or a bad index
        self.testapp.put_json(contents_href,
                              {'ntiid': question_ntiid2},
                              status=422)
        self.testapp.put_json(contents_href + '/index/1000',
                              {'ntiid': question_ntiid2},
                              status=409)
        self.testapp.put_json('%s/index/1000?ntiid=%s' % (contents_href, question_ntiid1 + 'xxxxxx'),
                              {'ntiid': question_ntiid2},
                              status=409)

    def _get_delete_url_suffix(self, index, ntiid):
        return '/ntiid/%s?index=%s' % (ntiid, index)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_delete(self):
        """
        Test deleting by index/ntiid in question sets.
        """
        # Initialize and install qset
        course_oid = self._get_course_oid()
        course = self.testapp.get('/dataserver2/Objects/%s' % course_oid)
        course = course.json_body
        evaluations_href = self.require_link_href_with_rel(course,
                                                          'CourseEvaluations')
        qset = self._load_questionset()
        ext_question = qset.get('questions')[0]
        qset = self.testapp.post_json(evaluations_href, qset, status=201)
        qset = qset.json_body
        contents_href = self.require_link_href_with_rel(qset,
                                                        VIEW_QUESTION_SET_CONTENTS)
        qset_ntiid = qset.get('NTIID')
        original_question_ntiids = self._get_question_ntiids(ext_obj=qset)

        # Insert/append
        inserted_question = self.testapp.post_json(contents_href, ext_question)
        new_question_ntiid = inserted_question.json_body.get('NTIID')
        question_ntiids = self._get_question_ntiids(qset_ntiid)
        assert_that(question_ntiids,
                    is_(original_question_ntiids + [new_question_ntiid]))

        # Now delete (incorrect index).
        delete_suffix = self._get_delete_url_suffix(0, new_question_ntiid)
        self.testapp.delete(contents_href + delete_suffix)
        assert_that(self._get_question_ntiids(qset_ntiid),
                    is_(original_question_ntiids))
        # No problem with multiple calls
        self.testapp.delete(contents_href + delete_suffix)
        assert_that(self._get_question_ntiids(qset_ntiid),
                    is_(original_question_ntiids))

        # Delete first object
        delete_suffix = self._get_delete_url_suffix(0,
                                                    original_question_ntiids[0])
        self.testapp.delete(contents_href + delete_suffix)
        assert_that(self._get_question_ntiids(qset_ntiid),
                    is_(original_question_ntiids[1:]))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_library_path_adapters(self):
        """
        Validate context provider adapters with API created assignments.
        """
        # Create base assessment object, enroll student, and set up vars for
        # test.
        course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
        course_oid = self._get_course_oid(course_ntiid)
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_ntiid = res.get('ntiid')
        enrolled_student = 'test_student'
        student_environ = self._create_and_enroll(enrolled_student,
                                                  course_ntiid)
        self.testapp.get('/dataserver2/LibraryPath?objectId=%s' % assignment_ntiid,
                         extra_environ=student_environ)

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            # TODO: need to fudge public access or enrollment here
            user = User.get_user(enrolled_student)
            course = find_object_with_ntiid(course_ntiid)
            assignment = find_object_with_ntiid(assignment_ntiid)
            get_joinable_contexts(assignment)
            get_top_level_contexts(assignment)
            get_top_level_contexts_for_user(assignment, user)
            get_hierarchy_context(assignment, user)
            get_hierarchy_context(assignment, user, context=course)

    @time_monotonically_increases
    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_submissions_for_unpublished(self):
        """
        We can only submit if an assignment is published, but we can
        always practice submit.
        """
        # Create base assessment object, enroll student, and set up vars for
        # test.
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        assignment_href = res.get('href')
        assignment_href = '%s?ntiid=%s' % (assignment_href, course_oid)
        practice_submission_href = self.require_link_href_with_rel(res,
                                                                   ASSESSMENT_PRACTICE_SUBMISSION)
        unpublish_href = self.require_link_href_with_rel(res, VIEW_UNPUBLISH)
        assignment_ntiid = res.get('ntiid')
        savepoint_href = '/dataserver2/Objects/%s/AssignmentSavepoints/sjohnson@nextthought.com/%s/Savepoint'
        savepoint_href = savepoint_href % (course_oid, assignment_ntiid)
        assert_that(res.get('version'), none())
        old_part = res.get('parts')[0]
        qset = old_part.get('question_set')
        qset_ntiid = qset.get('NTIID')
        question_ntiid = qset.get('questions')[0].get('ntiid')

        # Unpublish
        self.testapp.post(unpublish_href)

        # Get submission ready
        upload_submission = QUploadedFile(data=b'1234',
                                          contentType=b'image/gif',
                                          filename=u'foo.pdf')
        q_sub = QuestionSubmission(questionId=question_ntiid,
                                   parts=(upload_submission,))

        qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
                                              questions=(q_sub,))
        submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                          parts=(qs_submission,))
        submission = toExternalObject(submission)
        self.testapp.post_json(assignment_href, submission, status=403)
        self.testapp.post_json(savepoint_href, submission, status=403)
        self.testapp.post_json(practice_submission_href, submission)

    @time_monotonically_increases
    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_overdue_submissions_with_submission_buffer(self):
        """
        We can't submit of an assignment is overdue and past the submission buffer.
        """
        # Create base assessment object, enroll student, and set up vars for test
        editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        assignment = self._load_assignment()
        res = self.testapp.post_json(href, assignment, status=201)
        res = res.json_body
        publish_href = self.require_link_href_with_rel(res, VIEW_PUBLISH)
        assignment_href = res.get('href')
        assignment_href = '%s?ntiid=%s' % (assignment_href, course_oid)
        assignment_ntiid = res.get('ntiid')
        savepoint_href = '/dataserver2/Objects/%s/AssignmentSavepoints/sjohnson@nextthought.com/%s/Savepoint'
        savepoint_href = savepoint_href % (course_oid, assignment_ntiid)
        assert_that(res.get('version'), none())
        old_part = res.get('parts')[0]
        qset = old_part.get('question_set')
        qset_ntiid = qset.get('NTIID')
        question_ntiid = qset.get('questions')[0].get('ntiid')

        # Set the assignment end date and publish
        end_field = 'available_for_submission_ending'
        end_date_str = datetime.utcnow().isoformat()
        data = { end_field: end_date_str }
        res = self.testapp.put_json(assignment_href,
                                    data, extra_environ=editor_environ)
        self.testapp.post(publish_href)

        # Prepare submission
        upload_submission = QUploadedFile(data=b'1234',
                                          contentType=b'image/gif',
                                          filename=u'foo.pdf')
        q_sub = QuestionSubmission(questionId=question_ntiid,
                                   parts=(upload_submission,))

        qs_submission = QuestionSetSubmission(questionSetId=qset_ntiid,
                                              questions=(q_sub,))
        submission = AssignmentSubmission(assignmentId=assignment_ntiid,
                                          parts=(qs_submission,))
        submission = toExternalObject(submission)

        # Savepoints should work without a submission-buffer
        assignment_res = self.testapp.get(assignment_href)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        self.testapp.post_json(savepoint_href, submission)

        # Set the submission-buffer
        data = {'submission_buffer': 0}
        assignment = self.testapp.put_json(assignment_href,
                                    data, extra_environ=editor_environ)

        # Overdue savepoints and submissions should fail
        self.testapp.post_json(savepoint_href, submission, status=403)
        self.testapp.post_json(assignment_href, submission, status=403)

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_delete_self_assessments(self):
        course_oid = self._get_course_oid()
        evaluation_href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)
        qset = self._load_questionset()
        res = self.testapp.post_json(evaluation_href, qset, status=201)
        res = res.json_body
        qset_ntiid = res.get('NTIID')

        enrolled_student = 'test_student'
        self._create_and_enroll(enrolled_student, self.entry_ntiid)

        href = '/dataserver2/Objects/%s/@@self-assessments' % qset_ntiid
        student_environ = self._make_extra_environ(username=enrolled_student)
        self.testapp.delete_json(href, {'username': enrolled_student},
							     extra_environ=student_environ,
                                 status=403)

        res = self.testapp.delete_json(href, {'username': enrolled_student},
                                       status=200)
        assert_that(res.json_body,
                    has_entry('Items', has_entry(enrolled_student, 0)))

    def _submit_survey(self, item_id, ext_obj):
        # Make sure we're enrolled
        self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                               self.entry_ntiid,
                               status=201)

        course_res = self.testapp.get(COURSE_URL).json_body
        course_inquiries_link = \
            self.require_link_href_with_rel(course_res, 'CourseInquiries')

        submission_href = '%s/%s' % (course_inquiries_link, item_id)

        res = self.testapp.post_json(submission_href, ext_obj)
        survey_item_href = res.json_body['href']
        assert_that(survey_item_href, is_not(none()))

        res = self.testapp.get(submission_href)
        assert_that(res.json_body, has_entry('href', is_not(none())))
        assert_that(res.json_body, has_entry('submissions', is_(1)))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_editing_surveys(self, fake_active):
        fake_active.is_callable().returns(True)

        editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)

        # Create simple survey with freeresponse part
        fr_survey = self._load_survey()
        res = self.testapp.post_json(href, fr_survey, status=201)
        res = res.json_body
        survey_href = res.get('href')

        course_inquiries_link = \
            self.require_link_href_with_rel(res, 'publish')
        self.testapp.post_json(course_inquiries_link)

        # CAN implicitly create surveys during edits
        multichoice_poll = self._load_json_resource("poll-multiplechoice.json")
        res['questions'].append(multichoice_poll)

        with _register_counting_handler() as sub:
            res = self.testapp.put_json(survey_href,
                                        {'questions': res['questions']},
                                        extra_environ=editor_environ)

            # Ensure a single modification event
            assert_that(sub.count, is_(1))

        res = res.json_body
        assert_that(res.get('questions'), has_length(2))

        # CAN specify polls by OID
        questions = copy.copy(res['questions'])
        obj_ids = [question['OID'] for question in questions]
        res = self.testapp.put_json(survey_href,
                                    {'questions': [(obj_ids[0])]},
                                    extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('questions'), has_length(1))
        assert_that(res.get('questions')[0]['OID'], is_(obj_ids[0]))

        # CANNOT make structural changes with submissions
        survey_id = res['ntiid']
        poll_id = res['questions'][0]['ntiid']
        poll_sub = QPollSubmission(pollId=poll_id, parts=[0])
        submission = QSurveySubmission(surveyId=survey_id,
                                       questions=[poll_sub])

        ext_obj = to_external_object(submission)
        self._submit_survey(survey_id, ext_obj)

        #     1. Replaced with another existing poll
        self.testapp.put_json(survey_href,
                              {'questions': [questions[1]]},
                              extra_environ=editor_environ,
                              status=409)

        #     2. Replaced with a new poll with a different part
        self.testapp.put_json(survey_href,
                              {'questions': [multichoice_poll]},
                              extra_environ=editor_environ,
                              status=409)

        # Currently fails b/c we don't check that the part type is different
        # This is less of a concern if the app doesn't allow it, follow up with
        # app folks to see if this is something that will be allowed to happen,
        # as it's currently an open question as to how that's going to work
        #
        #     3. Same poll, different part
        # modeled_content_poll = self._load_json_resource("poll-modeledcontent.json")
        # new_poll = copy.deepcopy(questions[1])
        # new_poll['part'] = modeled_content_poll['part']
        #
        # self.testapp.put_json(survey_href,
        #                       {'questions': [new_poll]},
        #                       extra_environ=editor_environ,
        #                       status=409)

        # CAN make non-structural changes with submissions
        #     1. When poll is updated
        updated_question = copy.copy(res['questions'][0])
        updated_question['content'] = 'updated'
        res = self.testapp.put_json(survey_href,
                                    {'questions': [updated_question]},
                                    extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('questions'), has_length(1))
        assert_that(res.get('questions')[0]['content'], is_("updated"))

        poll_href = res.get('questions')[0]['href']
        poll_res = self.testapp.get(poll_href, extra_environ=editor_environ)
        poll_res = poll_res.json_body
        assert_that(poll_res['content'], is_("updated"))

        #     2. When part is updated
        updated_question['parts'][0]['content'] = "over there"
        res = self.testapp.put_json(survey_href,
                                    {'questions': [{
                                        'ntiid': updated_question['ntiid'],
                                        'parts': [
                                            updated_question['parts'][0]
                                        ]
                                    }]},
                                    extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('questions'), has_length(1))
        assert_that(res.get('questions')[0]['parts'][0]['content'], is_("over there"))

        poll_href = res.get('questions')[0]['href']
        poll_res = self.testapp.get(poll_href, extra_environ=editor_environ)
        poll_res = poll_res.json_body
        assert_that(poll_res['parts'][0]['content'], is_("over there"))

        # IS NOT updated with policy-only changes on poll
        last_modified = res['questions'][0]['Last Modified']
        res = self.testapp.put_json(survey_href,
                                    {'questions': [{
                                        'NTIID': res['questions'][0]['ntiid'],
                                        'available_for_submission_beginning': 1
                                    }]},
                                    extra_environ=editor_environ)
        res = res.json_body
        assert_that(res.get('questions'), has_length(1))
        assert_that(res.get('questions')[0]['Last Modified'], is_(last_modified))

        poll_href = res.get('questions')[0]['href']
        poll_res = self.testapp.get(poll_href, extra_environ=editor_environ)
        poll_res = poll_res.json_body
        assert_that(poll_res['Last Modified'], is_(last_modified))
        assert_that(poll_res['available_for_submission_beginning'], is_not(1))

    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_poll_preflight(self, fake_active):
        fake_active.is_callable().returns(True)

        enrolled_student = 'test_student'
        self._create_and_enroll(enrolled_student, self.entry_ntiid)
        student_environ = self._make_extra_environ(username=enrolled_student)
        editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
        instructor_environ = self._make_extra_environ(username="cs1323_instructor")

        course_oid = self._get_course_oid()
        course_href = '/dataserver2/Objects/%s' % quote(course_oid)
        href = '%s/CourseEvaluations' % course_href

        # Ensure preflight_create links are decorated or not as appropriate
        #       1. Shouldn't have link for student
        res = self.testapp.get(course_href, extra_environ=student_environ)
        self.forbid_link_with_rel(res.json_body, 'preflight_evaluations')

        #       2. Shouldn't have link for instructor (they can't add polls)
        res = self.testapp.get(course_href, extra_environ=instructor_environ)
        self.forbid_link_with_rel(res.json_body, 'preflight_evaluations')

        #       3. Should have link for editor
        res = self.testapp.get(course_href, extra_environ=editor_environ)
        preflight_evaluations = self.require_link_href_with_rel(res.json_body, 'preflight_evaluations')

        # Ensure we're getting appropriate validation from it
        multichoice_poll = self._load_json_resource("poll-multiplechoice.json")
        multichoice_poll['parts'] = []
        res = self.testapp.put_json(preflight_evaluations, multichoice_poll, status=422)
        res = res.json_body
        assert_that(res['code'], is_('TooShort'))

        # Ensure valid preflight doesn't create
        multichoice_poll = self._load_json_resource("poll-multiplechoice.json")
        self.testapp.put_json(preflight_evaluations, multichoice_poll, status=204)

        evaluations_res = self.testapp.get(href)
        evaluations_res = evaluations_res.json_body
        assert_that(evaluations_res['Items'], has_length(0))

        # Create and publish simple poll with multichoice part
        multichoice_poll = self._load_json_resource("poll-multiplechoice.json")
        res = self.testapp.post_json(href, multichoice_poll, status=201)

        res = res.json_body
        publish_link = \
            self.require_link_href_with_rel(res, 'publish')
        self.testapp.post_json(publish_link)

        # Ensure links are decorated or not as appropriate
        #       1. On poll creation
        preflight_href = self.require_link_href_with_rel(res, 'preflight_update')
        poll_href = self.require_link_href_with_rel(res, 'edit')
        original_content = res['content']

        #       2. Student shouldn't see them
        res = self.testapp.get(poll_href, extra_environ=student_environ)
        res = res.json_body
        self.forbid_link_with_rel(res, 'preflight_update')

        #       3. Should have link for instructor
        res = self.testapp.get(poll_href, extra_environ=instructor_environ)
        res = res.json_body
        self.require_link_href_with_rel(res, 'preflight_update')

        #       4. Should have link for editor
        res = self.testapp.get(poll_href, extra_environ=editor_environ)
        res = res.json_body
        self.require_link_href_with_rel(res, 'preflight_update')

        # Preflight valid part, without structural changes
        assert_that(original_content, is_not("updated_content"))
        res = self.testapp.put_json(preflight_href, {"content": "updated_content"})
        res = res.json_body
        assert_that(res['StructuralChanges'], is_(False))

        res = self.testapp.get(poll_href)
        res = res.json_body
        assert_that(res['content'], is_(original_content))

        # Preflight valid part, with structural changes
        new_part = copy.deepcopy(multichoice_poll['parts'][0])
        new_part["choices"] = ["a", "b", "c"]
        res = self.testapp.put_json(preflight_href, {"parts": [new_part]})
        res = res.json_body
        assert_that(res['StructuralChanges'], is_(True))

        # Preflight empty part, should 422
        res = self.testapp.put_json(preflight_href, {"parts": []}, status=422)
        res = res.json_body
        assert_that(res['code'], is_('TooShort'))


    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_edit_survey_with_submissions(self, fake_active):
        fake_active.is_callable().returns(True)

        editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
        course_oid = self._get_course_oid()
        href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)

        # Create simple survey with freeresponse part
        fr_survey = self._load_survey()
        res = self.testapp.post_json(href, fr_survey, status=201)
        res = res.json_body
        survey_href = res.get('href')

        publish_link = \
            self.require_link_href_with_rel(res, 'publish')
        self.testapp.post_json(publish_link)

        survey_id = res['ntiid']
        poll_id = res['questions'][0]['ntiid']
        self.submit_survey(survey_id, poll_id)

        # MUST CONFIRM structural changes with submissions
        multichoice_poll = self._load_json_resource("poll-multiplechoice.json")
        res['questions'].append(multichoice_poll)
        update = {
            'questions': res['questions']
        }

        res = self.testapp.put_json(survey_href,
                                    update,
                                    extra_environ=editor_environ,
                                    status=409)
        res = res.json_body
        force_href = self.require_link_href_with_rel(res, 'confirm')

        self.testapp.put_json(force_href,
                              update,
                              extra_environ=editor_environ)

    def submit_survey(self, survey_id, poll_id):
        submission = self._create_submission(survey_id,
                                             poll_id)
        ext_obj = to_external_object(submission)
        self._submit_survey(survey_id, ext_obj)

    def _create_submission(self, survey_id, poll_id):
        poll_sub = QPollSubmission(pollId=poll_id, parts=[0])
        submission = QSurveySubmission(surveyId=survey_id,
                                       questions=[poll_sub])
        return submission

    @WithSharedApplicationMockDS(testapp=True, users=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_edit_survey_remove_poll(self, fake_active):
        fake_active.is_callable().returns(True)

        course_oid = self._get_course_oid()
        eval_href = '/dataserver2/Objects/%s/CourseEvaluations' % quote(course_oid)

        # Create simple survey with freeresponse part
        fr_survey = self._load_survey()
        res = self.testapp.post_json(eval_href, fr_survey, status=201)
        survey_res = res.json_body
        survey_href = survey_res.get('href')
        create_poll_href = self.require_link_href_with_rel(survey_res, 'create_poll')

        # Create polls to use in the survey
        multichoice_poll = self._load_json_resource("poll-multiplechoice.json")
        res = self.testapp.post_json(create_poll_href, multichoice_poll, status=201)
        multichoice_href = res.json_body["href"]
        multichoice_ntiid = res.json_body["NTIID"]
        multichoice_oid = res.json_body["OID"]
        self.testapp.get(multichoice_href, status=200)

        modeledcontent_poll = self._load_json_resource("poll-modeledcontent.json")
        res = self.testapp.post_json(create_poll_href, modeledcontent_poll, status=201)
        modeledcontent_href = res.json_body["href"]
        modeledcontent_ntiid = res.json_body["NTIID"]
        self.testapp.get(modeledcontent_href, status=200)

        # Update survey with new polls
        survey_update = {
            "questions": [
                {"NTIID": survey_res["questions"][0]["NTIID"]},
                {"NTIID": multichoice_ntiid},
                {"NTIID": modeledcontent_ntiid},
            ]
        }
        res = self.testapp.put_json(survey_href, survey_update)
        res = res.json_body
        assert_that(res["questions"], has_length(3))

        # Reference second poll in another survey
        new_survey = {
            "MimeType": "application/vnd.nextthought.nasurvey",
            "questions": [
                multichoice_oid,
            ]
        }

        res = self.testapp.post_json(eval_href, new_survey, status=201)
        res = res.json_body
        assert_that(res["questions"], has_length(1))
        assert_that(res["questions"][0]["NTIID"], is_(multichoice_ntiid))

        # Update to remove new polls from survey
        survey_update = {
            "questions": [
                {"NTIID": survey_res["questions"][0]["NTIID"]},
            ]
        }
        res = self.testapp.put_json(survey_href, survey_update)
        res = res.json_body
        assert_that(res["questions"], has_length(1))

        # Multichoice poll still referenced in second survey
        self.testapp.get(multichoice_href, status=200)

        # Dereferenced poll should no longer be accessible
        self.testapp.get(modeledcontent_href, status=404)


@contextlib.contextmanager
def _register_counting_handler():
    gsm = component.getGlobalSiteManager()

    class _CountingSubscriber(object):
        def __init__(self):
            self.count = 0

        def __call__(self, _poll, _event):
            self.count += 1

    handler = _CountingSubscriber()
    gsm.registerHandler(handler, (IQPoll, IObjectModifiedEvent))
    try:
        yield handler
    finally:
        gsm.unregisterHandler(handler, (IQPoll, IObjectModifiedEvent))
