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
from hamcrest import contains
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import contains_string
does_not = is_not

import time
import fudge
from six import StringIO
from zipfile import ZipFile
from datetime import datetime
from six.moves.urllib_parse import unquote

from zope import component

from zope.securitypolicy.principalrole import principalRoleManager

import ZODB

from nti.app.assessment.feedback import UsersCourseAssignmentHistoryItemFeedback

from nti.assessment import parts
from nti.assessment import response
from nti.assessment import submission

from nti.assessment.assignment import QAssignment
from nti.assessment.assignment import QAssignmentPart

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.assessment.question import QQuestion
from nti.assessment.question import QQuestionSet

from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.users.users import User

from nti.externalization import internalization

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.app.assessment import VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationTestLayer
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class _RegisterFileAssignmentLayer(InstructedCourseApplicationTestLayer):

    @classmethod
    def setUp(cls):
        question_set_id = u"tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
        assignment_ntiid = u"tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle"
        question_id = u'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.qid.aristotle.1'
        cls.question_set_id = question_set_id
        cls.assignment_id = assignment_ntiid
        cls.question_id = question_id

        def install_questions():
            lib = component.getUtility(IContentPackageLibrary)

            part = parts.QFilePart()
            part.allowed_mime_types = (u'*/*',)
            part.allowed_extensions = u'*'
            question = QQuestion(parts=[part])
            question.ntiid = cls.question_id

            component.getSiteManager().registerUtility(question, provided=IQuestion,
                                                       name=question_id)

            question_set = QQuestionSet(questions=(question,))
            question_set.ntiid = cls.question_set_id
            component.provideUtility(question_set, provides=IQuestionSet,
                                     name=cls.question_set_id)

            # Works with auto_grade true or false.
            assignment_part = QAssignmentPart(question_set=question_set,
                                              auto_grade=False)
            assignment = QAssignment(parts=(assignment_part,))
            cls.assignment = assignment
            assignment.__name__ = assignment.ntiid = cls.assignment_id

            old_assignment = component.getSiteManager().queryUtility(IQAssignment,
                                                                     name=cls.assignment_id)
            cls.old_assignment = old_assignment
            if old_assignment is not None:
                component.getSiteManager().unregisterUtility(old_assignment,
                                                             provided=IQAssignment,
                                                             name=cls.assignment_id)
            component.getSiteManager().registerUtility(assignment,
                                                       provided=IQAssignment,
                                                       name=cls.assignment_id)

            # Also make sure this assignment is found in the assignment index
            # at some container
            lesson_page_id = u"tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:02.01_RequiredReading"
            cls.lesson_page_id = lesson_page_id
            lesson = lib.pathToNTIID(lesson_page_id)[-1]
            assignment.__parent__ = lesson
            assignment.publish()
            IQAssessmentItemContainer(lesson).append(assignment)

        cls.database = ZODB.DB(ApplicationTestLayer._storage_base,
                               database_name='Users')

        @mock_dataserver.WithMockDS(database=cls.database)
        def _sync():
            with mock_dataserver.mock_db_trans(site_name='platform.ou.edu'):
                install_questions()
        _sync()

    @classmethod
    def tearDown(cls):
        # MUST implement
        # Re setUp super class?
        pass

    @classmethod
    def setUpTest(cls):
        pass

    @classmethod
    def tearDownTest(cls):
        pass


class TestAssignmentFileGrading(ApplicationLayerTest):

    layer = _RegisterFileAssignmentLayer

    question_id = None
    assignment_id = None
    question_set_id = None
    lesson_page_id = None
    default_origin = 'http://janux.ou.edu'

    def setUp(self):
        super(TestAssignmentFileGrading, self).setUp()
        self.assignment_id = _RegisterFileAssignmentLayer.assignment_id
        self.lesson_page_id = _RegisterFileAssignmentLayer.lesson_page_id
        self.question_set_id = _RegisterFileAssignmentLayer.question_set_id
        self.question_id = _RegisterFileAssignmentLayer.question_id

    def _check_submission(self, res, history=None):
        assert_that(res.status_int, is_(201))
        assert_that(res.json_body,
                    has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
        assert_that(res.json_body,
                    has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))
        assert_that(res.json_body,
                    has_entry(StandardExternalFields.MIMETYPE,
                              'application/vnd.nextthought.assessment.assignmentsubmissionpendingassessment'))

        assert_that(res.json_body,
                    has_entry('ContainerId', self.assignment_id))
        assert_that(res.json_body, has_key('NTIID'))

        assert_that(res,
                    has_property('location', contains_string('Objects/')))

        # This object can be found in my history
        if history:
            __traceback_info__ = history
            res = self.testapp.get(history)
            assert_that(res.json_body,
                        has_entry('href', contains_string(unquote(history))))
            assert_that(res.json_body, has_entry('Items', has_length(1)))
            assert_that(res.json_body, has_entry('lastViewed', 0))
        else:
            # Because we're not enrolled...actually, we shouldn't
            # have been able to submit...this is here to make sure something
            # breaks when acls change
            res = self._fetch_user_url('/Courses/EnrolledCourses/CLC3403/AssignmentHistories/sjohnsen@nextthought.com',
                                       status=404)
        return res

    def _create_and_enroll(self, course_id='tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'):
        uploaded_file = response.QUploadedFile(data=b'1234',
                                               contentType=b'image/gif',
                                               filename=u'image.gif')
        q_sub = submission.QuestionSubmission(questionId=self.question_id,
                                              parts=(uploaded_file,))

        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id,
                                              questions=(q_sub,))
        asg_submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                              parts=(qs_submission,))
        GIF_DATAURL = 'data:image/gif;base64,R0lGODlhCwALAIAAAAAA3pn/ZiH5BAEAAAEALAAAAAALAAsAAAIUhA+hkcuO4lmNVindo7qyrIXiGBYAOw=='

        ext_obj = to_external_object(asg_submission)
        ext_obj['parts'][0]['questions'][0]['parts'][0]['value'] = GIF_DATAURL

        assert_that(internalization.find_factory_for(ext_obj),
                    is_(not_none()))

        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     course_id,
                                     status=201)

        course_rel = self.require_link_href_with_rel(res.json_body, 'CourseInstance')
        course_res = self.testapp.get(course_rel).json_body
        enrollment_history_link = self.require_link_href_with_rel(
            res.json_body, 'AssignmentHistory')
        self.require_link_href_with_rel(course_res,
                                       'AssignmentHistory')
        assessments_rel = self.require_link_href_with_rel(course_res,
                                                          'Assessments')

        res = self.testapp.post_json('%s/%s' % (assessments_rel, self.assignment_id),
                                     ext_obj)
        history_res = self._check_submission(res, enrollment_history_link)

        return history_res, assessments_rel, course_rel

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.assessment.views.history_views.CourseAssignmentSubmissionBulkFileDownloadView._get_assignments')
    def test_posting_and_bulk_downloading_file(self, mock_get_assignments):
        fake_assignment = fudge.Fake()
        fake_assignment.has_attr(__name__=self.assignment_id)
        mock_get_assignments.is_callable().returns([fake_assignment])
        
        history_res, assessments_rel, course_rel = self._create_and_enroll()

        # Now we should be able to find and download our data
        submission = history_res.json_body['Items'].values()[0]['Submission']
        submitted_file_part = submission['parts'][0]['questions'][0]['parts'][0]
        assert_that(submitted_file_part, has_key('url'))
        assert_that(submitted_file_part, has_key('value'))
        assert_that(submitted_file_part['url'],
                    is_(submitted_file_part['value']))
        assert_that(submitted_file_part, has_key('download_url'))

        # Once directly, as is consistent with the way that avatars, etc work
        download_res = self.testapp.get(submitted_file_part['url'])
        assert_that(download_res, has_property('content_type', 'image/gif'))
        assert_that(download_res, has_property('content_length', 61))
        assert_that(download_res,
                    has_property('content_disposition', is_not(none())))

        # Then for download, both directly and without the trailing /view
        paths = [submitted_file_part['download_url']]
        url = submitted_file_part['url']
        idx = url.find('/@@view')
        url = url[:idx] if idx != -1 else url
        paths.append(url)

        for path in paths:
            download_res = self.testapp.get(path)
            assert_that(download_res, has_property('content_length', 61))
            assert_that(download_res,
                           has_property('content_type', 'image/gif'))
            assert_that(download_res,
                           has_property('content_disposition', not_none()))

        # Our default user happens to have admin perms to fetch the files
        res = self.testapp.get('%s/%s' % (assessments_rel, self.assignment_id))
        bulk_href = self.require_link_href_with_rel(res.json_body,
                                                   'ExportFiles')

        res = self.testapp.get(bulk_href)

        assert_that(res.content_disposition,
                    is_('attachment; filename="CLC3403_assignment.zip"'))

        data = res.body
        io = StringIO(data)
        zipfile = ZipFile(io, 'r')

        name = 'sjohnson@nextthought.com-0-0-0-image.gif'
        assert_that(zipfile.namelist(), contains(name))
        info = zipfile.getinfo(name)
        # Rounding means the second data may not be accurate
        assert_that(info.date_time[:5],
                    is_(download_res.last_modified.timetuple()[:5]))
        
        # Test the course-level download
        course_res = self.testapp.get(course_rel).json_body
        bulk_href = self.require_link_href_with_rel(course_res, VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD)
        
        res = self.testapp.get(bulk_href)

        assert_that(res.content_disposition,
                    is_('attachment; filename="CLC3403_CLC3403_LawAndJustice.zip"'))
        
        data = res.body
        io = StringIO(data)
        zipfile = ZipFile(io, 'r')

        name = 'tag_nextthought.com_2011-10_OU-NAQ-CLC3403_LawAndJustice.naq.asg_QUIZ1_aristotle/sjohnson@nextthought.com-0-0-0-image.gif'
        assert_that(zipfile.namelist(), contains(name))
        info = zipfile.getinfo(name)
        # Rounding means the second data may not be accurate
        assert_that(info.date_time[:5],
                    is_(download_res.last_modified.timetuple()[:5]))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.assessment.history.get_policy_for_assessment',
                 'nti.app.assessment.history.get_available_for_submission_ending')
    def test_student_nuclear_option(self, mock_gpa, mock_se):
        mock_gpa.is_callable().with_args().returns(
            {'student_nuclear_reset_capable': True}
        )
        mock_se.is_callable().with_args().returns(
            datetime.utcfromtimestamp(time.time() + 20000)
        )

        # Enroll in section 1, which lets this happen for this object
        cid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice_SubInstances_01'
        history_res, _, _ = self._create_and_enroll(course_id=cid)

        item = history_res.json_body['Items'][self.assignment_id]
        item_href = item['href']
        # Initially, we have the ability to delete it ourself
        link = self.link_with_rel(item, 'edit')
        assert_that(link, is_(not_none()))
        assert_that(link, has_entry('method', 'DELETE'))

        history_feedback_container_href = item['Feedback']['href']
        # If we put some feedback, that goes away
        feedback = UsersCourseAssignmentHistoryItemFeedback(body=['Some feedback'])
        ext_feedback = to_external_object(feedback)
        feedback_res = self.testapp.post_json(history_feedback_container_href,
                                              ext_feedback,
                                              status=201)

        item_res = self.testapp.get(item_href)
        item = item_res.json_body
        self.forbid_link_with_rel(item, 'edit')

        # and the old link doesn't work either
        self.testapp.delete(link['href'], status=403)

        # deleting the feedback gets it back
        self.testapp.delete(feedback_res.json_body['href'])

        item_res = self.testapp.get(item_href)
        item = item_res.json_body
        item_edit_href = self.require_link_href_with_rel(item, 'edit')

        # whereupon we can do so
        self.testapp.delete(item_edit_href, status=204)
        self.testapp.get(item_href, status=404)
        self.testapp.get(history_feedback_container_href, status=404)

    @WithSharedApplicationMockDS(users=('content_admin',), testapp=True)
    @fudge.patch('nti.app.assessment.history.get_policy_for_assessment',
                 'nti.app.assessment.history.get_available_for_submission_ending')
    def admin_permissions(self, mock_gpa, mock_se):
        """
        Make sure our global content admin cannot edit feedback.
        """
        mock_gpa.is_callable().with_args().returns(
            {'student_nuclear_reset_capable': True}
        )
        mock_se.is_callable().with_args().returns(
            datetime.utcfromtimestamp(time.time() + 20000)
        )

        # Enroll and get our history item and feedback
        cid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice_SubInstances_01'
        history_res, _, _ = self._create_and_enroll(course_id=cid)

        item = history_res.json_body['Items'][self.assignment_id]
        item_href = item['href']
        # Initially, we have the ability to delete it ourself
        link = self.link_with_rel(item, 'edit')
        assert_that(link, is_(not_none()))
        assert_that(link, has_entry('method', 'DELETE'))

        history_feedback_container_href = item['Feedback']['href']
        # If we put some feedback, that goes away
        feedback = UsersCourseAssignmentHistoryItemFeedback(body=['Some feedback'])
        ext_feedback = to_external_object(feedback)
        feedback_res = self.testapp.post_json(history_feedback_container_href,
                                              ext_feedback,
                                              status=201)
        feedback_href = feedback_res.json_body.get('href')

        # Create our admin
        admin_environ = self._make_extra_environ(username='content_admin')

        res = self.testapp.get('/dataserver2/users/content_admin/Courses/AdministeredCourses',
                               extra_environ=admin_environ)
        assert_that(res.json_body, has_entry('Items', has_length(0)))

        with mock_dataserver.mock_db_trans(self.ds):
            user = User.get_user('content_admin')
            assert_that(user, not_none())
            principalRoleManager.assignRoleToPrincipal(ROLE_CONTENT_ADMIN.id,
                                                       'content_admin',
                                                       check=False)

        # Global content admin cannot fetch history item or feedback
        self.testapp.get(item_href, extra_environ=admin_environ, status=403)
        self.testapp.get(feedback_href,
                         extra_environ=admin_environ, status=403)
