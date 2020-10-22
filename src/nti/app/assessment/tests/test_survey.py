#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

import os
import json

from csv import DictReader

import fudge

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import is_not as does_not
from hamcrest import has_key
from hamcrest import has_item
from hamcrest import has_entry
from hamcrest import has_entries
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import contains_string

from nti.testing.matchers import validly_provides

from six import StringIO

from six.moves.urllib_parse import unquote

import weakref

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiryItem

from nti.app.assessment.survey import UsersCourseInquiry
from nti.app.assessment.survey import UsersCourseInquiries
from nti.app.assessment.survey import UsersCourseInquiryItem

from nti.app.assessment.tests import AssessmentLayerTest
from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import DISCLOSURE_SUBMISSION

from nti.assessment.survey import QPollSubmission
from nti.assessment.survey import QSurveySubmission

from nti.contenttypes.completion.interfaces import ICompletedItemContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.users.users import User

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid


class TestSurvey(AssessmentLayerTest):

    def test_provides(self):
        surveys = UsersCourseInquiries()
        survey = UsersCourseInquiry()
        survey.__parent__ = surveys

        survey.owner = weakref.ref(User(u'sjohnson@nextthought.com'))
        item = UsersCourseInquiryItem()
        item.creator = u'foo'
        item.__parent__ = survey
        assert_that(item, validly_provides(IUsersCourseInquiryItem))

        assert_that(survey, validly_provides(IUsersCourseInquiry))
        assert_that(IUser(item), is_(survey.owner))
        assert_that(IUser(survey), is_(survey.owner))

    def test_record(self):
        course_survey = UsersCourseInquiry()
        submission = QSurveySubmission(surveyId=u'b', questions=())
        assert_that(submission, validly_provides(IQSurveySubmission))

        item = course_survey.recordSubmission(submission)
        assert_that(item, has_property('Submission', is_(submission)))
        assert_that(item, has_property('__name__', is_(submission.surveyId)))
        assert_that(item.__parent__, is_(course_survey))
        assert_that(course_survey, has_length(1))

        course_survey.removeSubmission(submission)
        assert_that(course_survey, has_length(0))


COURSE_NTIID = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
COURSE_URL = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice'


class TestSurveyViews(RegisterAssignmentLayerMixin, ApplicationLayerTest):

    layer = RegisterAssignmentsForEveryoneLayer

    features = ('assignments_for_everyone',)

    default_origin = 'http://janux.ou.edu'
    default_username = 'outest75'

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    def test_fetching_entire_survey_collection(self):

        outest_environ = self._make_extra_environ(username='outest5')
        outest_environ.update({'HTTP_ORIGIN': 'http://janux.ou.edu'})

        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)

        default_enrollment_savepoints_link = \
            self.require_link_href_with_rel(res.json_body, 'InquiryHistory')

        expected = ('/dataserver2/users/' +
                    self.default_username +
                    '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/Inquiries/' +
                    self.default_username)

        assert_that(unquote(default_enrollment_savepoints_link),
                    is_(unquote(expected)))

        res = self.testapp.post_json('/dataserver2/users/outest5/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201,
                                     extra_environ=outest_environ)

        user2_enrollment_history_link = \
            self.require_link_href_with_rel(res.json_body, 'InquiryHistory')

        # each can fetch his own
        self.testapp.get(default_enrollment_savepoints_link)
        self.testapp.get(user2_enrollment_history_link,
                         extra_environ=outest_environ)

        # but they can't get each others
        self.testapp.get(default_enrollment_savepoints_link,
                         extra_environ=outest_environ,
                         status=403)
        self.testapp.get(user2_enrollment_history_link, status=403)

    def _check_submission(self, res, inquiry=None, containerId=None):
        assert_that(res.status_int, is_(201))
        assert_that(res.json_body, has_key('Submission'))
        assert_that(res.json_body, has_entry('href', is_not(none())))

        submission = res.json_body['Submission']
        assert_that(submission,
                    has_entry(StandardExternalFields.CREATED_TIME, is_(float)))

        assert_that(submission,
                    has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))

        assert_that(submission,
                    has_entry(StandardExternalFields.MIMETYPE,
                              'application/vnd.nextthought.assessment.userscourseinquiryitem'))

        assert_that(submission, has_key('Submission'))
        submission = submission['Submission']
        if containerId:
            assert_that(submission, has_entry('ContainerId', containerId))

        assert_that(submission,
                    has_entry(StandardExternalFields.CREATED_TIME, is_(float)))

        assert_that(submission,
                    has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))

        if inquiry:
            __traceback_info__ = inquiry
            inquiry_res = self.testapp.get(inquiry)

            assert_that(inquiry_res.json_body,
                        has_entry('href', contains_string(unquote(inquiry))))

            assert_that(inquiry_res.json_body,
                        has_entry('Items', has_length(1)))

            items = list(inquiry_res.json_body['Items'].values())
            assert_that(items[0], has_key('href'))
        else:
            self._fetch_user_url('/Courses/EnrolledCourses/CLC3403/Inquiries/' +
                                 self.default_username, status=404)

    def _test_submission(self, item_id, ext_obj, enroll=True):
        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201 if enroll else 200)

        course_res = self.testapp.get(COURSE_URL).json_body
        enrollment_inquiries_link = \
            self.require_link_href_with_rel(res.json_body, 'InquiryHistory')

        course_inquiries_history_link = \
            self.require_link_href_with_rel(course_res, 'InquiryHistory')

        course_inquiries_link = \
            self.require_link_href_with_rel(course_res, 'CourseInquiries')

        submission_href = '%s/%s' % (course_inquiries_link, item_id)

        expected = ('/dataserver2/users/' +
                    self.default_username +
                    '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/Inquiries/' +
                    self.default_username)
        assert_that(unquote(enrollment_inquiries_link),
                    is_(unquote(expected)))

        expected = ('/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice/Inquiries/' +
                    self.default_username)
        assert_that(unquote(course_inquiries_history_link),
                    is_(unquote(expected)))

        # Both survey links are equivalent and work; and both are empty before
        # I submit
        for link in course_inquiries_history_link, enrollment_inquiries_link:
            survey_res = self.testapp.get(link)
            assert_that(survey_res.json_body,
                        has_entry('Items', has_length(0)))

        self.testapp.get(submission_href + '/Submission', status=404)

        post_res = self.testapp.post_json(submission_href, ext_obj)
        post_res_json = post_res.json_body
        survey_item_href = post_res_json['href']
        assert_that(survey_item_href, is_not(none()))
        self._check_submission(post_res, enrollment_inquiries_link, item_id)

        res = self.testapp.get(survey_item_href)
        assert_that(res.json_body, has_entry('href', is_not(none())))

        res = self.testapp.get(submission_href)
        assert_that(res.json_body, has_entry('href', is_not(none())))
        assert_that(res.json_body, has_entry('submissions', is_(1)))

        # Both survey links are equivalent and work
        for link in course_inquiries_history_link, enrollment_inquiries_link:
            surveys_res = self.testapp.get(link)
            assert_that(surveys_res.json_body,
                        has_entry('Items', has_length(1)))
            assert_that(surveys_res.json_body,
                        has_entry('Items', has_key(item_id)))

        # simply adding get us to an item
        href = surveys_res.json_body['href'] + '/' + item_id
        res = self.testapp.get(href)
        assert_that(res.json_body, has_entry('href', is_not(none())))

        # we cannot delete
        self.testapp.delete(survey_item_href, status=403)
        self.testapp.get(survey_item_href, status=200)
        return post_res_json

    @WithSharedApplicationMockDS(users=('outest5', 'sjohnson@nextthought.com'), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_survey(self, fake_active):
        fake_active.is_callable().returns(True)

        poll_sub = QPollSubmission(pollId=self.poll_id, parts=[0])
        submission = QSurveySubmission(surveyId=self.survey_id,
                                       questions=[poll_sub])

        ext_obj = to_external_object(submission)
        del ext_obj['Class']
        assert_that(ext_obj,
                    has_entry('MimeType', 'application/vnd.nextthought.assessment.surveysubmission'))

        self._test_submission(self.survey_id, ext_obj)

        # Validate completion
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            course = find_object_with_ntiid(COURSE_NTIID)
            course = ICourseInstance(course)
            container = ICompletedItemContainer(course)
            user_container = container.get(self.default_username)
            assert_that(user_container, has_item(self.survey_id))

        self._reset_survey(self.survey_id)

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            course = find_object_with_ntiid(COURSE_NTIID)
            course = ICourseInstance(course)
            container = ICompletedItemContainer(course)
            user_container = container.get(self.default_username)
            assert_that(user_container, does_not(has_item(self.survey_id)))

    def _reset_survey(self, inquiry_id):
        course_res = self.testapp.get(COURSE_URL).json_body
        course_inquiries_link = self.require_link_href_with_rel(course_res,
                                                                'CourseInquiries')
        reset_href = '%s/%s/@@Reset' % (course_inquiries_link, inquiry_id)
        admin_env = self._make_extra_environ(user='sjohnson@nextthought.com')
        self.testapp.post(reset_href, extra_environ=admin_env)

    def _load_json_resource(self, resource):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            result = json.load(fp)
            return result

    def _load_survey(self):
        return self._load_json_resource("survey-freeresponse.json")

    def _create_survey(self, disclosure=None):
        admin_environ = self._make_extra_environ(
            username='sjohnson@nextthought.com')

        course_res = self.testapp.get(COURSE_URL,
                                      extra_environ=admin_environ).json_body
        evals_href = self.require_link_href_with_rel(course_res, 'CourseEvaluations')

        fr_survey = self._load_survey()

        if disclosure:
            fr_survey['disclosure'] = disclosure

        res = self.testapp.post_json(evals_href, fr_survey, status=201,
                                     extra_environ=admin_environ)
        res = res.json_body

        # Publish
        publish_link = \
            self.require_link_href_with_rel(res, 'publish')
        publish_res = self.testapp.post_json(publish_link, extra_environ=admin_environ)

        return publish_res.json_body

    def _enroll(self, username, course_ntiid=None, origin=None):
        test_student_environ = self._make_extra_environ(
            username=username)

        if origin:
            test_student_environ.update({'HTTP_ORIGIN': origin})

        self.testapp.post_json('/dataserver2/users/' + username + '/Courses/EnrolledCourses',
                               course_ntiid or COURSE_NTIID,
                               status=201,
                               extra_environ=test_student_environ)

    def _submit_survey(self, ext_survey, enroll=True):
        poll_subs = [QPollSubmission(pollId=poll['NTIID'], parts=['answer'])
                     for poll in ext_survey['questions']]

        survey_id = ext_survey['NTIID']
        submission = QSurveySubmission(surveyId=survey_id,
                                       questions=poll_subs)

        ext_obj = to_external_object(submission)
        del ext_obj['Class']
        assert_that(ext_obj,
                    has_entry('MimeType', 'application/vnd.nextthought.assessment.surveysubmission'))

        return self._test_submission(survey_id, ext_obj, enroll=enroll)

    @WithSharedApplicationMockDS(users=('test_user', 'sjohnson@nextthought.com',),
                                 testapp=True,
                                 default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_survey_results_disclosure_submission(self, fake_active):
        """
        Ensure a disclosure of `submission` works as expected
        """
        fake_active.is_callable().returns(True)

        # Enroll everyone for test
        for username in self.users:
            self._enroll(username)

        survey_res = self._create_survey(disclosure=DISCLOSURE_SUBMISSION)
        survey_href = survey_res['href']

        # No results to aggregate yet, even for admin
        self.forbid_link_with_rel(survey_res, 'Aggregated')

        # Shouldn't be able to see results until after submission
        student_survey_res = self.testapp.get(survey_href)
        student_survey_res = student_survey_res.json_body
        self.forbid_link_with_rel(student_survey_res, 'Aggregated')

        # Submit with default user (outest75)
        submission_res = self._submit_survey(survey_res, enroll=False)
        assert_that(submission_res, has_key('Aggregated'))

        # Now both default user and admin should have a link for results
        student_survey_res = self.testapp.get(survey_href)
        student_survey_res = student_survey_res.json_body
        results_link = self.require_link_href_with_rel(student_survey_res, 'Aggregated')

        # Ensure we can actually fetch them
        results_res = self.testapp.get(results_link).json_body
        assert_that(results_res['questions'][0]['parts'][0]['Total'], is_(1))
        assert_that(results_res['questions'][0]['parts'][0]['Results'],
                    has_entries({
                        "answer": 1
                    }))

        admin_environ = self._make_extra_environ(username='sjohnson@nextthought.com')
        admin_survey_res = self.testapp.get(survey_href,
                                              extra_environ=admin_environ)
        admin_survey_res = admin_survey_res.json_body
        self.require_link_href_with_rel(admin_survey_res, 'Aggregated')

        # Different user still has no Aggregated link
        alt_student_env = self._make_extra_environ(username='test_user')
        alt_survey_res = self.testapp.get(survey_href, extra_environ=alt_student_env)
        alt_survey_res = alt_survey_res.json_body
        self.forbid_link_with_rel(alt_survey_res, 'Aggregated')

        # User w/ no submission shouldn't be able to fetch results
        self.testapp.get(results_link, extra_environ=alt_student_env, status=403)

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_poll(self, fake_active):
        fake_active.is_callable().returns(True)

        submission = QPollSubmission(pollId=self.poll_id, parts=[0])

        ext_obj = to_external_object(submission)
        del ext_obj['Class']
        assert_that(ext_obj,
                    has_entry('MimeType', 'application/vnd.nextthought.assessment.pollsubmission'))

        self._test_submission(self.poll_id, ext_obj)

    @WithSharedApplicationMockDS(users=('test_student'), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive',
                 'nti.app.assessment.views.survey_views._date_str_from_timestamp')
    def test_submission_metadata(self, fake_active, fake_date):
        fake_active.is_callable().returns(True)
        fake_date.is_callable().returns('05-10-2017')
        test_student_environ = self._make_extra_environ(
            username='test_student')

        test_student_environ.update({'HTTP_ORIGIN': 'http://janux.ou.edu'})
        instructor_environ = self._make_extra_environ(username='harp4162')

        # make sure we're enrolled
        self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                               COURSE_NTIID,
                               status=201)

        self.testapp.post_json('/dataserver2/users/' + 'test_student' + '/Courses/EnrolledCourses',
                               COURSE_NTIID,
                               status=201,
                               extra_environ=test_student_environ)

        submission_href = \
            '/dataserver2/++etc++hostsites/platform.ou.edu/++etc++site/Courses/Fall2013/CLC3403_LawAndJustice' + \
            '/CourseInquiries/%s' % self.survey_id

        survey_inquiry_link = \
            '/dataserver2/++etc++hostsites/platform.ou.edu/++etc++site/Courses/Fall2013/CLC3403_LawAndJustice/' + \
            'CourseInquiries/' + self.survey_id + '/@@SubmissionMetadata'

        # If we check this when no students have submitted, we should
        # get an empty spreadsheet.
        res = self.testapp.get(survey_inquiry_link,
                               extra_environ=instructor_environ)
        assert_that(res.body,
                    is_('username,realname,email,submission_time\r\n'))

        poll_sub = QPollSubmission(pollId=self.poll_id, parts=[0])
        submission = QSurveySubmission(surveyId=self.survey_id,
                                       questions=[poll_sub])

        # submit as a student
        ext_obj = to_external_object(submission)
        res = self.testapp.post_json(submission_href, ext_obj)

        # Now we should see that this student submitted
        res = self.testapp.get(survey_inquiry_link,
                               extra_environ=instructor_environ)
        result = DictReader(StringIO(res.body))
        result = [x for x in result]
        assert_that(result,
                    has_item(has_entries('username', 'outest75',
                                         'submission_time', '05-10-2017',
                                         'email', '',
                                         'realname', '')))

        # submit as our other test student, and then that should show up in the
        # report as well
        self.testapp.post_json(submission_href,
                               ext_obj,
                               extra_environ=test_student_environ)

        res = self.testapp.get(survey_inquiry_link,
                               extra_environ=instructor_environ)
        result = DictReader(StringIO(res.body))
        result = [x for x in result]
        assert_that(result,
                    has_item(has_entries('username', 'outest75',
                                         'submission_time', '05-10-2017',
                                         'email', '',
                                         'realname', '')))
        assert_that(result,
                    has_item(has_entries('username', 'test_student',
                                         'submission_time', '05-10-2017',
                                         'email', '',
                                         'realname', '')))

    @WithSharedApplicationMockDS(users=('test_student'), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive',
                 'nti.app.assessment.views.survey_views._date_str_from_timestamp')
    def test_survey_csv_report(self, fake_active, fake_date):
        fake_active.is_callable().returns(True)
        fake_date.is_callable().returns('05-10-2017')
        test_student_environ = self._make_extra_environ(
            username='test_student')
        test_student_environ.update({'HTTP_ORIGIN': 'http://janux.ou.edu'})
        instructor_environ = self._make_extra_environ(username='harp4162')

        # make sure we're enrolled
        self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                               COURSE_NTIID,
                               status=201)

        self.testapp.post_json('/dataserver2/users/' + 'test_student' + '/Courses/EnrolledCourses',
                               COURSE_NTIID,
                               status=201,
                               extra_environ=test_student_environ)

        survey_ntiid = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.survey:KNOWING_aristotle"
        survey_href = '/dataserver2/Objects/' + survey_ntiid
        submission_href = \
            '/dataserver2/++etc++hostsites/platform.ou.edu/++etc++site/Courses/Fall2013/CLC3403_LawAndJustice' + \
            '/CourseInquiries/%s' % self.survey_id

        # If we check this when no students have submitted, we should
        # just get back the header row.
        res = self.testapp.get(survey_href + '/InquiryReport.csv',
                               extra_environ=instructor_environ)
        question_one_content = "I have a nice, hot apple pie to divide among my four friends. I have to decide how to split up the delicious dessert."
        assert_that(res.body,
                    is_('"%s"\r\n' % question_one_content))

        # Make sure that we can't get this report if we're a student.
        self.testapp.get(survey_href + '/InquiryReport.csv',
                         extra_environ=test_student_environ,
                         status=403)

        poll_sub = QPollSubmission(
            pollId=self.poll_id, parts=[0])
        submission = QSurveySubmission(surveyId=self.survey_id,
                                       questions=[poll_sub])

        # submit as a student
        ext_obj = to_external_object(submission)
        res = self.testapp.post_json(submission_href, ext_obj)

        res = self.testapp.get(survey_href + '/InquiryReport.csv',
                               extra_environ=instructor_environ)

        # "Distributive" is the first of the multiple choice options. Since we
        # chose the 0th choice, we expect to get "Distributive" back as the
        # label.
        assert_that(res.body,
                    is_('"%s"\r\nDistributive\r\n' % question_one_content))

        # Submit again as a different student with a different choice
        poll_sub = QPollSubmission(pollId=self.poll_id,
                                   parts=[1])
        submission = QSurveySubmission(surveyId=self.survey_id,
                                       questions=[poll_sub])
        ext_obj = to_external_object(submission)
        self.testapp.post_json(submission_href,
                               ext_obj,
                               extra_environ=test_student_environ)

        # Test including the username column now. This will ensure that
        # the rows are sorted by username.
        res = self.testapp.get(survey_href + '/InquiryReport.csv?include_usernames=True',
                               extra_environ=instructor_environ)
        assert_that(res.body,
                    is_('user,"%s"\r\noutest75,Distributive\r\ntest_student,Corrective\r\n' % question_one_content))

        # TODO: add cases for different types of survey questions.
