#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904
import json
import os

from hamcrest import has_entries
from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import all_of
from hamcrest import has_key
from hamcrest import not_
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import assert_that
does_not = is_not

import fudge

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.tests import mock_dataserver

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.app.assessment.tests import AssessmentLayerTest
from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.products.courseware.tests import PersistentInstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission
from nti.assessment.submission import QuestionSubmission

from nti.externalization import to_external_object

from nti.externalization.tests import externalizes

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid

GIF_DATAURL = 'data:image/gif;base64,R0lGODlhCwALAIAAAAAA3pn/ZiH5BAEAAAEALAAAAAALAAsAAAIUhA+hkcuO4lmNVindo7qyrIXiGBYAOw=='


class TestDecorators(AssessmentLayerTest):

    def test_upload_file(self):
        ext_obj = {
            'MimeType': 'application/vnd.nextthought.assessment.uploadedfile',
            'value': GIF_DATAURL,
            'filename': u'ichigo.gif',
            'name': u'ichigo.gif'
        }
        assert_that(find_factory_for(ext_obj), is_(not_none()))
        internal = find_factory_for(ext_obj)()
        update_from_external_object(internal, ext_obj, require_updater=True)
        assert_that(internal, externalizes(all_of(has_key('FileMimeType'),
                                                  has_key('filename'),
                                                  has_key('name'),
                                                  has_entry('url', none()),
                                                  has_key('CreatedTime'),
                                                  has_key('Last Modified'))))
        # But we have no URL because we're not in a connection anywhere

    def test_file_upload2(self):
        # Temporary workaround for iPad bug.
        ext_obj = {
            'MimeType': 'application/vnd.nextthought.assessment.quploadedfile',
            'value': GIF_DATAURL,
            'filename': u'ichigo.gif',
            'name': u'ichigo.gif'
        }

        assert_that(find_factory_for(ext_obj), is_(not_none()))
        internal = find_factory_for(ext_obj)()
        update_from_external_object(internal, ext_obj, require_updater=True)
        assert_that(internal, externalizes(all_of(has_key('FileMimeType'),
                                                  has_key('filename'),
                                                  has_key('name'),
                                                  has_entry('url', none()),
                                                  has_key('CreatedTime'),
                                                  has_key('Last Modified'))))


class TestCoursePreviewExternalization(ApplicationLayerTest):
    """
    Validate courses in preview mode hide features from enrolled students,
    but still expose them for admins.
    """

    layer = PersistentInstructedCourseApplicationTestLayer

    default_origin = 'http://platform.ou.edu'

    course_href = '/dataserver2/Objects/tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
    course_ntiid = None

    enrolled_courses_href = '/dataserver2/users/test_student/Courses/EnrolledCourses'
    enrollment_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

    def _do_enroll(self, environ):
        self.testapp.post_json(self.enrolled_courses_href,
                               {'ntiid': self.enrollment_ntiid},
                               status=201,
                               extra_environ=environ)

    def _get_course_ext(self, environ):
        if not self.course_ntiid:
            entry = self.testapp.get(self.course_href, extra_environ=environ)
            entry = entry.json_body
            self.course_ntiid = entry.get('CourseNTIID')
        result = self.testapp.get('/dataserver2/Objects/%s' % self.course_ntiid,
                                  extra_environ=environ)
        return result.json_body

    def _test_course_ext(self, environ, is_visible=True):
        if is_visible:
            link_check = self.require_link_href_with_rel
        else:
            link_check = self.forbid_link_with_rel
        course_ext = self._get_course_ext(environ)

        for rel in ('AssignmentSavepoints', 'AssignmentHistory',
                    'AssignmentsByOutlineNode', 'NonAssignmentAssessmentItemsByOutlineNode',
                    'InquiryHistory'):
            link_check(course_ext, rel)

    @WithSharedApplicationMockDS(users=('test_student',), testapp=True)
    @fudge.patch('nti.app.products.courseware.utils.PreviewCourseAccessPredicate._is_preview')
    def test_preview_decorators(self, mock_is_preview):
        mock_is_preview.is_callable().returns(False)
        student_env = self._make_extra_environ('test_student')
        instructor_env = self._make_extra_environ('harp4162')
        self._do_enroll(student_env)

        # Base case
        self._test_course_ext(student_env, is_visible=True)

        # Preview mode
        mock_is_preview.is_callable().returns(True)
        self._test_course_ext(student_env, is_visible=False)

        # Preview mode w/instructor
        self._test_course_ext(instructor_env, is_visible=True)


class TestAssessmentDecorators(ApplicationLayerTest):

    layer = PersistentInstructedCourseApplicationTestLayer

    default_origin = 'http://platform.ou.edu'

    course_href = '/dataserver2/Objects/tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
    course_ntiid = None

    enrolled_courses_href = '/dataserver2/users/test_student/Courses/EnrolledCourses'
    enrollment_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

    def _do_enroll(self, environ):
        self.testapp.post_json(self.enrolled_courses_href,
                               {'ntiid': self.enrollment_ntiid},
                               status=201,
                               extra_environ=environ)

    def _get_assess_ext(self, environ):
        if not self.course_ntiid:
            entry = self.testapp.get(self.course_href, extra_environ=environ)
            entry = entry.json_body
            self.course_ntiid = entry.get('CourseNTIID')
        result = self.testapp.get('/dataserver2/Objects/%s/AssignmentsByOutlineNode' % self.course_ntiid,
                                  extra_environ=environ)
        return result.json_body.get('Items')

    def _test_course_ext(self, environ, is_editor):
        edit_check = self.require_link_href_with_rel if is_editor else self.forbid_link_with_rel

        assess_items = self._get_assess_ext(environ)

        for item in assess_items:
            for rel in ('date-edit-start', 'date-edit-end', 'audit_log', 'schema'):
                edit_check(item, rel)

    @WithSharedApplicationMockDS(users=('test_student',), testapp=True)
    def test_assess_edit_links(self):
        student_env = self._make_extra_environ('test_student')
        instructor_env = self._make_extra_environ('jmadden')
        editor_env = self._make_extra_environ('harp4162')
        self._do_enroll(student_env)

        self._test_course_ext(student_env, is_editor=False)
        self._test_course_ext(instructor_env, is_editor=False)
        self._test_course_ext(editor_env, is_editor=True)


class TestQuestionSetSolutionDecoration(ApplicationLayerTest):

    layer = PersistentInstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

    self_assessment_ntiid = u'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle'

    @classmethod
    def catalog_entry(cls):
        return find_object_with_ntiid(cls.entry_ntiid)

    def _load_json_resource(self, resource):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            result = json.load(fp)
            return result

    def _load_qset_submission(self):
        return self._load_json_resource("self_assessment_submission.json")

    def _create_and_enroll(self, username, entry_ntiid=None):
        entry_ntiid = entry_ntiid if entry_ntiid else self.entry_ntiid
        with mock_dataserver.mock_db_trans(self.ds):
            self._create_user(username=username)
        environ = self._make_extra_environ(username=username)
        admin_environ = self._make_extra_environ(
            username=self.default_username)
        enroll_url = '/dataserver2/CourseAdmin/UserCourseEnroll'
        res = self.testapp.post_json(enroll_url,
                               {'ntiid': entry_ntiid,
                                'username': username},
                               extra_environ=admin_environ)
        return environ

    @WithSharedApplicationMockDS(testapp=True, users=True)
    def test_qset_soln_decoration(self):

        with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
            entry = self.catalog_entry()
            course = ICourseInstance(entry)
            course_ntiid = to_external_ntiid_oid(course)

        instructor_environ = self._make_extra_environ(username='harp4162')
        instructor_environ['HTTP_ORIGIN'] = 'http://platform.ou.edu'

        student_environ = self._create_and_enroll('student1')
        course_url = '/dataserver2/Objects/%s' % course_ntiid
        self_assessment_url = '/dataserver2/Objects/%s' % (self.self_assessment_ntiid,)

        # Student shouldn't have solutions prior to submission
        self_assessment_res = self.testapp.get(self_assessment_url,
                                               extra_environ=student_environ).json_body
        assert_that(self_assessment_res['questions'][0]['parts'][0],
                    not_(has_entry('solutions', not_none())))

        # Instructors should always see solutions
        self_assessment_res = self.testapp.get(self_assessment_url,
                                               extra_environ=instructor_environ).json_body
        assert_that(self_assessment_res['questions'][0]['parts'][0],
                    has_entry('solutions', not_none()))

        # Student should have solutions after submission, on both
        # assessed question and question set
        self_assessment_submission_url = '%s/Pages' % (course_url,)
        submission = self._load_qset_submission()
        submit_res = self.testapp.post_json(self_assessment_submission_url,
                                            submission,
                                            extra_environ=student_environ).json_body
        assert_that(submit_res['questions'][0]['parts'][0], has_entries({
            'solutions': not_none(),
            'explanation': not_none(),
            'assessedValue': not_none(),
        }))

        post_self_assessment_res = self.testapp.get(self_assessment_url,
                                                    extra_environ=student_environ).json_body
        assert_that(post_self_assessment_res['questions'][0]['parts'][0], has_entries({
            'solutions': not_none(),
            'explanation': not_none(),
        }))

        # Ensure solutions returned when fetching submission via UGD for page
        accept_type = 'application/vnd.nextthought.pageinfo+json'
        pageinfo_url = '/dataserver2/Objects/%s?course=%s&type=%s' % (
            self.self_assessment_ntiid,
            course_ntiid,
            accept_type
        )
        res = self.testapp.get(pageinfo_url,
                               headers={'Accept': accept_type},
                               extra_environ=student_environ).json_body
        page_ugd_url = self.require_link_href_with_rel(res, 'UserGeneratedData')
        page_ugd_url = '%s?sortOn=lastModified&sortOrder=descending' % page_ugd_url
        page_ugd_res = self.testapp.get(page_ugd_url,
                                        extra_environ=student_environ).json_body
        assert_that(page_ugd_res['Items'][0]['questions'][0]['parts'][0],
                    has_entries({
                        'solutions': not_none(),
                        'explanation': not_none(),
                        'assessedValue': not_none(),
                    }))

        # Also check PracticeSubmission for instructors have assessed values
        instructor_assessment_res = self.testapp.get(self_assessment_url,
                                                     extra_environ=instructor_environ).json_body
        practice_sub_url = self.require_link_href_with_rel(instructor_assessment_res,
                                                           'PracticeSubmission')
        submit_res = self.testapp.post_json(practice_sub_url,
                                            submission,
                                            extra_environ=instructor_environ).json_body
        assert_that(submit_res['questions'][0]['parts'][0],
                    has_entries({
                        'solutions': not_none(),
                        'explanation': not_none(),
                        'assessedValue': not_none(),
                    }))




class TestAssignmentSolutionDecoration(RegisterAssignmentLayerMixin, ApplicationLayerTest):

    layer = RegisterAssignmentsForEveryoneLayer
    features = ('assignments_for_everyone',)

    default_origin = 'http://janux.ou.edu'
    default_username = 'outest75'

    course_href = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice'
    course_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

    self_assessment_ntiid = u'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle'

    def _verify_solutions(self,
                          assignment_submit_rel,
                          ext_submission,
                          enrollment_history_link,
                          instructor_environ,
                          has_student_solutions=False):
        submission_res = self.testapp.post_json(assignment_submit_rel, ext_submission).json_body
        assessed_part = submission_res['parts'][0]['questions'][0]['parts'][0]
        check = is_ if has_student_solutions else not_
        assert_that(assessed_part, check(has_key('assessedValue')))
        assert_that(assessed_part, has_entries({
            'solutions': check(not_none()),
            'explanation': check(not_none()),
        }))

        res = self.testapp.get(enrollment_history_link).json_body
        assessed_part = res['Items'].values()[0]['Items'][0]['pendingAssessment']['parts'][0]['questions'][0]['parts'][0]
        assert_that(assessed_part, check(has_key('assessedValue')))
        assert_that(assessed_part, has_entries({
            'solutions': check(not_none()),
            'explanation': check(not_none()),
        }))

        # Ensure instructor gets all solutions
        res = self.testapp.get(enrollment_history_link, extra_environ=instructor_environ).json_body
        assessed_part = res['Items'].values()[0]['Items'][0]['pendingAssessment']['parts'][0]['questions'][0]['parts'][0]
        assert_that(assessed_part, has_entries({
            'solutions': not_none(),
            'explanation': not_none(),
            'assessedValue': not_none(),
        }))

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    @fudge.patch('nti.app.assessment.common.evaluations.get_completed_item',
                 'nti.app.assessment.decorators.assignment.get_completed_item')
    def test_multisubmission_solutions(self,
                                       mock_completed_item_common,
                                       mock_completed_item_decorators,
                                       ):
        # Student shouldn't get solutions if it hasn't been completed
        mock_completed_item_common.is_callable().returns(None)
        mock_completed_item_decorators.is_callable().returns(None)

        success_item = fudge.Fake()
        success_item.has_attr(Success=True)
        fail_item = fudge.Fake()
        fail_item.has_attr(Success=False)

        # Sends an assignment through the application by posting to the
        # assignment
        question_ntiid = u'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.qid.aristotle.1'
        q_sub = QuestionSubmission(questionId=question_ntiid,
                                   parts=(0,))
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id,
                                              questions=(q_sub,))
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)

        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     self.course_ntiid,
                                     status=201)

        enrollment_history_link = self.require_link_href_with_rel(res.json_body,
                                                                  'AssignmentHistory')
        course_res = self.testapp.get(self.course_href).json_body
        course_instance_link = course_res['href']
        assignment_submit_rel = '%s/%s/%s' % (course_instance_link,
                                              'Assessments',
                                              self.assignment_id)

        instructor_environ = self._make_extra_environ(username='harp4162')
        assignment_url = '%s/Assessments/%s' % (course_instance_link,
                                                self.assignment_id)
        self.testapp.put_json(assignment_url,
                              {
                                  'max_submissions': 3,
                                  'submission_priority': 'HIGHEST_GRADE'
                              },
                              extra_environ=instructor_environ)

        # Need to start
        assignment_res = self.testapp.get(assignment_submit_rel)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        self._verify_solutions(assignment_submit_rel,
                               ext_obj,
                               enrollment_history_link,
                               instructor_environ,
                               has_student_solutions=False)

        # Provide student with failed completion
        assignment_res = self.testapp.get(assignment_submit_rel)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        mock_completed_item_common.is_callable().returns(fail_item)
        mock_completed_item_decorators.is_callable().returns(fail_item)

        self._verify_solutions(assignment_submit_rel,
                               ext_obj,
                               enrollment_history_link,
                               instructor_environ,
                               has_student_solutions=False)

        # Provide student with successful completion
        assignment_res = self.testapp.get(assignment_submit_rel)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)

        mock_completed_item_common.is_callable().returns(None)
        mock_completed_item_decorators.is_callable().returns(success_item)

        self._verify_solutions(assignment_submit_rel,
                               ext_obj,
                               enrollment_history_link,
                               instructor_environ,
                               has_student_solutions=True)
