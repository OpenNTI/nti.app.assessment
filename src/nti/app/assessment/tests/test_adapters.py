#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=protected-access,too-many-public-methods

from hamcrest import is_
from hamcrest import is_not
from hamcrest import raises
from hamcrest import has_key
from hamcrest import calling
from hamcrest import contains
from hamcrest import not_none
from hamcrest import has_item
from hamcrest import has_items
from hamcrest import has_entry
from hamcrest import ends_with
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_entries
from hamcrest import has_property
from hamcrest import contains_string
does_not = is_not

from nti.testing.matchers import is_empty
from nti.testing.matchers import validly_provides

import fudge
import datetime
from six.moves import urllib_parse
from six.moves.urllib_parse import quote
from six.moves.urllib_parse import unquote

from zope import component

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import ConstraintNotSatisfied

from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.adapters import _begin_assessment_for_assignment_submission

from nti.app.assessment.feedback import UsersCourseAssignmentHistoryItemFeedback

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories

from nti.app.assessment.tests import RegisterAssignmentLayer
from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.contentlibrary import LIBRARY_PATH_GET_VIEW

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from nti.assessment.submission import AssignmentSubmission
from nti.assessment.submission import QuestionSetSubmission

from nti.contentfragments.interfaces import IPlainTextContentFragment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.users.users import User

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.mimetype.mimetype import nti_mimetype_with_class

from nti.ntiids.ntiids import find_object_with_ntiid

COURSE_NTIID = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
COURSE_URL = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice'


class TestAssignmentGrading(RegisterAssignmentLayerMixin, ApplicationLayerTest):

    layer = RegisterAssignmentsForEveryoneLayer
    features = ('assignments_for_everyone',)

    default_origin = 'http://janux.ou.edu'
    default_username = 'outest75'

    @WithSharedApplicationMockDS
    def test_wrong_id(self):
        submission = AssignmentSubmission(assignmentId=u'b')
        # A component lookup error for the assignment using adapter syntax
        # turns into a TypeError
        assert_that(calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
                    raises(TypeError))

        assert_that(calling(_begin_assessment_for_assignment_submission).with_args(submission),
                    raises(LookupError))

    @WithSharedApplicationMockDS
    def test_wrong_parts(self):
        submission = AssignmentSubmission(assignmentId=self.assignment_id)

        with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
            assert_that(calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
                        raises(ConstraintNotSatisfied, 'parts'))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.assessment.adapters.get_course_from_request')
    def test_before_open(self, mock_find):
        from nti.contenttypes.courses.assignment import EmptyAssignmentDateContext
        mock_find.is_callable().returns(EmptyAssignmentDateContext(None))
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(
            assignmentId=self.assignment_id, parts=(qs_submission,))

        # Open tomorrow
        with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
            assignment = component.getUtility(IQAssignment, self.assignment_id)
            assignment.available_for_submission_beginning = (
                datetime.datetime.utcnow() + datetime.timedelta(days=1)
            )
            try:
                assert_that(calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
                            raises(ConstraintNotSatisfied, 'early'))
            finally:
                assignment = component.getUtility(IQAssignment, self.assignment_id)
                assignment.available_for_submission_beginning = None

    @WithSharedApplicationMockDS(users=True)
    def test_pending(self):
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        with mock_dataserver.mock_db_trans(self.ds, site_name='janux.ou.edu'):
            # No creator
            assert_that(calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
                        raises(TypeError))

            user = User.get_user(self.extra_environ_default_user)
            submission.creator = user
            pending = IQAssignmentSubmissionPendingAssessment(submission)
            assert_that(pending,
                        validly_provides(IQAssignmentSubmissionPendingAssessment))

        # If we try again, we fail
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))
        with mock_dataserver.mock_db_trans(self.ds, site_name='janux.ou.edu'):
            user = User.get_user(self.extra_environ_default_user)
            submission.creator = user
            assert_that(calling(IQAssignmentSubmissionPendingAssessment).with_args(submission),
                        raises(NotUnique, 'already submitted'))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    @fudge.patch('nti.app.assessment.views.history_views.get_current_metadata_attempt_item')
    def test_pending_application_user_data(self, fudge_meta):
        fudge_meta.is_callable().returns(True)
        # Sends an assignment through the application by sending it to the
        # user.
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)
        # If these are posted to the user, they should have a container ID,
        # but because we are not storing them on the user, it doesn't matter...
        # it gets replacen anyway
        # to anything)
        ext_obj['ContainerId'] = u'tag:nextthought.com,2011-10:mathcounts-HTML-MN.2012.0'
        res = self.testapp.post_json('/dataserver2/Objects/%s?course=%s' % (self.assignment_id, COURSE_NTIID),
                                     ext_obj)

        self._check_submission(res)

    @WithSharedApplicationMockDS(users=True, testapp=True, default_authenticate=True)
    def test_pending_application_assignment_not_enrolled(self):

        # Sends an assignment through the application by posting to the assignment,
        # but we're not enrolled in a course using that assignment, so it fails
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))
        ext_obj = to_external_object(submission)

        self.testapp.post_json('/dataserver2/Objects/%s' % self.assignment_id,
                               ext_obj,
                               status=422)

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    def test_fetching_entire_assignment_history_collection(self):
        # Only the owner and instructor can, others cannot
        instructor_environ = self._make_extra_environ(username='harp4162')
        outest_environ = self._make_extra_environ(username='outest5')
        outest_environ.update({'HTTP_ORIGIN': 'http://janux.ou.edu'})

        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)

        default_enrollment_history_link = self.require_link_href_with_rel(res.json_body,
                                                                          'AssignmentHistory')
        expected = ('/dataserver2/users/' +
                    self.default_username +
                    '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/AssignmentHistories/' +
                    self.default_username)
        assert_that(unquote(default_enrollment_history_link),
                    is_(unquote(expected)))

        res = self.testapp.post_json('/dataserver2/users/outest5/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201,
                                     extra_environ=outest_environ)

        user2_enrollment_history_link = self.require_link_href_with_rel(res.json_body,
                                                                        'AssignmentHistory')

        # each can fetch his own
        self.testapp.get(default_enrollment_history_link)
        self.testapp.get(user2_enrollment_history_link,
                         extra_environ=outest_environ)

        # as can the instructor
        self.testapp.get(default_enrollment_history_link,
                         extra_environ=instructor_environ)
        self.testapp.get(user2_enrollment_history_link,
                        extra_environ=instructor_environ)

        # but they can't get each others
        self.testapp.get(default_enrollment_history_link,
                         extra_environ=outest_environ,
                         status=403)
        self.testapp.get(user2_enrollment_history_link, status=403)

    def _check_submission(self, res, history=None, last_viewed=0):
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
        assert_that(res.json_body,
                    has_entry('href', contains_string('Objects/')))

        assert_that(res, has_property('location', contains_string('Objects/')))

        # This object can be found in my history
        if history:
            res = self.testapp.get(history)
            assert_that(res.json_body,
                        has_entry('href', contains_string(unquote(history))))
            assert_that(res.json_body, has_entry('Items', has_length(1)))
            assert_that(res.json_body, has_entry('lastViewed', last_viewed))
        else:
            # Because we're not enrolled...actually, we shouldn't
            # have been able to submit...this is here to make sure something
            # breaks when acls change
            href = '/Courses/EnrolledCourses/CLC3403/AssignmentHistories/'
            res = self._fetch_user_url(href + self.default_username, status=404)

        return res

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive',
                 'nti.app.assessment.common.evaluations.get_completed_item')
    def test_pending_application_assignment(self, fake_active, mock_completed_item):
        # make it look like the course is in session so notables work
        fake_active.is_callable().returns(True)
        # Completed the assignment prevents future submissions
        mock_completed_item.is_callable().returns(None)

        # Sends an assignment through the application by posting to the
        # assignment
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)
        del ext_obj['Class']
        assert_that(ext_obj,
                    has_entry('MimeType', 'application/vnd.nextthought.assessment.assignmentsubmission'))
        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)

        course_res = self.testapp.get(COURSE_URL).json_body
        enrollment_history_link = self.require_link_href_with_rel(res.json_body,
                                                                  'AssignmentHistory')
        course_history_link = self.require_link_href_with_rel(course_res,
                                                              'AssignmentHistory')
        course_instance_link = course_res['href']

        expected = ('/dataserver2/users/' +
                    self.default_username +
                    '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/AssignmentHistories/' +
                    self.default_username)
        assert_that(unquote(enrollment_history_link),
                    is_(unquote(expected)))

        expected = ('/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice/AssignmentHistories/' +
                    self.default_username)
        assert_that(unquote(course_history_link), is_(unquote(expected)))

        # Both history links are equivalent and work; and both are empty before
        # I submit
        for link in course_history_link, enrollment_history_link:
            history_res = self.testapp.get(link)
            assert_that(history_res.json_body,
                        has_entry('Items', has_length(0)))

        assignment_submit_rel = '%s/%s/%s' % (course_instance_link,
                                              'Assessments',
                                              self.assignment_id)
        # Need to start
        assignment_res = self.testapp.get(assignment_submit_rel)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        res = self.testapp.post_json(assignment_submit_rel, ext_obj)
        self._check_submission(res, enrollment_history_link)

        history_res = self._check_submission(res, course_history_link)
        container = history_res.json_body['Items'][self.assignment_id]
        history_item_href = container['Items'][0]['href']
        last_viewed_href = self.require_link_href_with_rel(history_res.json_body,
                                                           'lastViewed')
        container = history_res.json_body['Items'].values()[0]
        history_feedback_container_href = container['Items'][0]['Feedback']['href']

        # The user can send some feedback
        feedback = UsersCourseAssignmentHistoryItemFeedback(body=[u'Some feedback'])
        ext_feedback = to_external_object(feedback)

        res = self.testapp.post_json(history_feedback_container_href,
                                     ext_feedback,
                                     status=201)

        # Library path gives us course, submission, feedback.
        library_path = self.require_link_href_with_rel(res.json_body, LIBRARY_PATH_GET_VIEW)
        library_path_res = self.testapp.get(library_path)
        library_path_res = library_path_res.json_body
        assert_that(library_path_res, has_length(1))
        library_path_res = library_path_res[0]
        assert_that(library_path_res, has_length(3))
        classes = [x.get('Class') for x in library_path_res]
        assert_that(classes, has_items('CourseInstance',
                                       'UsersCourseAssignmentHistoryItem',
                                       'UsersCourseAssignmentHistoryItemFeedback'))
        feedback_ntiid = res.json_body.get('NTIID')
        assert_that(library_path_res[-1].get('NTIID'), is_(feedback_ntiid))

        # He can edit it
        feedback_item_edit_link = self.require_link_href_with_rel(res.json_body,
                                                                  'edit')
        new_feedback = dict(res.json_body)
        new_feedback['body'] = [u'Other feedback']

        res = self.testapp.put_json(feedback_item_edit_link, new_feedback)
        assert_that(res.json_body, has_entry('body', ['Other feedback']))

        # Both history links are equivalent and work
        for link in course_history_link, enrollment_history_link:
            history_res = self.testapp.get(link)
            assert_that(history_res.json_body,
                        has_entry('Items', has_length(1)))
            container = history_res.json_body['Items'].values()[0]
            assert_that(container['Items'], has_length(1))
            item = container['Items'][0]
            feedback = item['Feedback']
            assert_that(feedback, has_entry('Items', has_length(1)))
            assert_that(feedback['Items'],
                        has_item(has_entry('body', ['Other feedback'])))
            assert_that(feedback['Items'], has_item(has_entry('href',
                                                              ends_with('AssignmentHistories/' +
                                                                        self.default_username +
                                                                        unquote('/tag%3Anextthought.com%2C2011-10%3AOU-NAQ-CLC3403_LawAndJustice.naq.asg%3AQUIZ1_aristotle/UsersCourseAssignmentHistoryItem/Feedback/0')))))

        # We can modify the view date by putting to the field
        res = self.testapp.put_json(last_viewed_href, 1234)
        history_res = self.testapp.get(course_history_link)
        assert_that(history_res.json_body, has_entry('lastViewed', 1234))

        # Of course, trying to PUT directly to the object 404s (not 500, we've
        # seen clients attempt this in the wild)
        self.testapp.put_json(course_history_link + '?_dc=1234/lastViewed',
                              2345, status=404)

        instructor_environ = self._make_extra_environ(username='harp4162')

        outest_environ = self._make_extra_environ(username='outest5')
        outest_environ.update({'HTTP_ORIGIN': 'http://janux.ou.edu'})
        self.testapp.post_json('/dataserver2/users/outest5/Courses/EnrolledCourses',
                               COURSE_NTIID,
                               status=201,
                               extra_environ=outest_environ)

        # The instructor sees our submission in his activity view, as well as
        # the feedback
        activity_link = course_instance_link + '/CourseActivity'
        res = self.testapp.get(activity_link, extra_environ=instructor_environ)
        assert_that(res.json_body, has_entry('TotalItemCount', 2))
        assert_that(res.json_body['Items'],
                    contains(has_entries('Class', 'UsersCourseAssignmentHistoryItemFeedback',
                                         'AssignmentId', 'tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.asg:QUIZ1_aristotle',
                                         'SubmissionCreator', self.default_username),
                    has_entry('Class', 'AssignmentSubmission')))

        # This feedback should be notable for the instructor
        notable_res2 = self.fetch_user_recursive_notable_ugd(username='harp4162',
                                                             extra_environ=instructor_environ)
        assert_that(notable_res2.json_body, has_entry('TotalItemCount', 1))
        assert_that(notable_res2.json_body['Items'],
                    has_item(has_entry('body', has_item('Other feedback'))))

        # Now delete it before we go on.
        self.testapp.delete(feedback_item_edit_link)

        # The instructor can add his own feedback
        feedback = UsersCourseAssignmentHistoryItemFeedback(body=[u'A reply to your feedback'])
        ext_feedback = to_external_object(feedback)
        inst_feedback_res = self.testapp.post_json(history_feedback_container_href,
                                                   ext_feedback,
                                                   status=201,
                                                   extra_environ=instructor_environ)

        # At that point, it shows up as a notable item for the user...
        notable_res = self.fetch_user_recursive_notable_ugd()
        assert_that(notable_res.json_body, has_entry('TotalItemCount', 1))
        assert_that(notable_res.json_body, has_entry('Items',
                                                     contains(has_entry('Creator', 'harp4162'))))

        # ... though not for the instructor...
        notable_res2 = self.fetch_user_recursive_notable_ugd(username='harp4162',
                                                             extra_environ=instructor_environ)
        assert_that(notable_res2.json_body, has_entry('TotalItemCount', 0))

        # ... or any other enrolled user...
        notable_res3 = self.fetch_user_recursive_notable_ugd(username='outest5',
                                                             extra_environ=outest_environ)
        assert_that(notable_res3.json_body, has_entry('TotalItemCount', 0))

        # (who, BTW, can't see the item)
        self.testapp.get(history_item_href,
                         extra_environ=outest_environ, status=403)
        # although we can
        self.testapp.get(history_item_href)

        # We can each delete our own feedback item and it vanishes completely
        # Wouldn't a deleted object placeholder be better?
        # self.testapp.delete(feedback_item_edit_link)
        self.testapp.delete(self.require_link_href_with_rel(inst_feedback_res.json_body, 'edit'),
                            extra_environ=instructor_environ)
        for link in course_history_link, enrollment_history_link:
            history_res = self.testapp.get(link)
            submission_container = history_res.json_body['Items'].values()[0]
            item = submission_container['Items'][0]
            feedback = item['Feedback']
            assert_that(feedback, has_entry('Items', has_length(0)))

        # It's gone from the instructor's activity
        res = self.testapp.get(activity_link, extra_environ=instructor_environ)
        assert_that(res.json_body, has_entry('TotalItemCount', 1))
        assert_that(res.json_body['Items'],
                    contains(has_entry('Class', 'AssignmentSubmission')))

        # it's gone as a notable item
        notable_res = self.fetch_user_recursive_notable_ugd()
        assert_that(notable_res.json_body, has_entry('TotalItemCount', 0))

        # The instructor can delete our submission
        self.testapp.delete(item['href'],
                            extra_environ=instructor_environ, status=204)
        # Which empties out the activity
        res = self.testapp.get(activity_link, extra_environ=instructor_environ)
        assert_that(res.json_body, has_entry('TotalItemCount', 0))
        assert_that(res.json_body, has_entry('Items', is_empty()))

        # Whereupon we can submit again
        # Need to start
        assignment_res = self.testapp.get(assignment_submit_rel)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        res = self.testapp.post_json(assignment_submit_rel, ext_obj)
        self._check_submission(res, enrollment_history_link, 1234)

        # The instructor can reset all submission
        reset_href = '/dataserver2/Objects/%s/@@Reset' % quote(self.assignment_id)
        res = self.testapp.post_json(reset_href,
                                     extra_environ=instructor_environ, status=200)
        assert_that(res.json_body['NTIID'] == self.assignment_id)

        res = self.testapp.get(activity_link, extra_environ=instructor_environ)
        assert_that(res.json_body, has_entry('TotalItemCount', 0))
        assert_that(res.json_body, has_entry('Items', is_empty()))

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_instructor_pending_application_assignment(self, fake_active):
        """
        Validate an instructor can practice submitting without persisting it.
        """
        fake_active.is_callable().returns(True)
        instructor_environ = self._make_extra_environ(username='harp4162')

        # Sends an assignment through the application by posting to the
        # assignment
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id)
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)
        del ext_obj['Class']
        assert_that(ext_obj,
                    has_entry('MimeType', 'application/vnd.nextthought.assessment.assignmentsubmission'))

        history_href = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice/AssignmentHistories/harp4162/tag%3Anextthought.com%2C2011-10%3AOU-NAQ-CLC3403_LawAndJustice.naq.asg%3AQUIZ1_aristotle'
        self.testapp.get(history_href,
                         extra_environ=instructor_environ, status=404)

        # Practice assignment
        assignment = self.testapp.get('/dataserver2/Objects/%s?course=%s' % (self.assignment_id, COURSE_NTIID),
                                      extra_environ=instructor_environ)
        practice_href = self.require_link_href_with_rel(
            assignment.json_body, ASSESSMENT_PRACTICE_SUBMISSION)

        res = self.testapp.post_json(practice_href,
                                     ext_obj,
                                     extra_environ=instructor_environ)
        res = res.json_body
        assert_that(res.get('MimeType'),
                    is_('application/vnd.nextthought.assessment.assignmentsubmissionpendingassessment'))

        # Nothing persisted.
        history_href = self.require_link_href_with_rel(res,
                                                       'AssignmentHistoryItem')
        self.testapp.get(history_href,
                         extra_environ=instructor_environ, status=404)

        # Practice assessment
        self_assess = self.testapp.get('/dataserver2/Objects/%s' % self.question_set_id,
                                       extra_environ=instructor_environ)
        practice_href = self.require_link_href_with_rel(self_assess.json_body,
                                                        ASSESSMENT_PRACTICE_SUBMISSION)

        ext_obj = to_external_object(qs_submission)
        del ext_obj['Class']
        res = self.testapp.post_json(practice_href,
                                     ext_obj,
                                     extra_environ=instructor_environ)
        res = res.json_body
        assert_that(res.get('MimeType'),
                    is_('application/vnd.nextthought.assessment.assessedquestionset'))

        # No results for qset.
        qsets_url = '/dataserver2/users/harp4162/Pages(%s)/UserGeneratedData?accept=application,vnd.nextthought.assessment.assessedquestionset' % self.question_set_id
        self.testapp.get(qsets_url,
                         extra_environ=instructor_environ, status=404)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_assignment_items_view(self):

        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)
        enrollment_history_link = self.require_link_href_with_rel(res.json_body,
                                                                  'AssignmentHistory')

        course_res = self.testapp.get(COURSE_URL).json_body
        enrollment_assignments = self.require_link_href_with_rel(course_res,
                                                                 'AssignmentsByOutlineNode')
        self.require_link_href_with_rel(course_res,
                                        'AssignmentsByOutlineNode')

        res = self.testapp.get(enrollment_assignments)
        assert_that(res.json_body['Items'], has_entry(self.lesson_page_id,
                                                      contains(has_entries('Class', 'Assignment',
                                                                           'NTIID', self.assignment_id))))
        # The due date strips these
        assg = res.json_body['Items'][self.lesson_page_id][0]
        for part in assg['parts']:
            question_set = part['question_set']
            for question in question_set['questions']:
                for qpart in question['parts']:
                    assert_that(qpart, has_entries('solutions', None,
                                                   'explanation', None))

        # (Except if we're the instructor)
        instructor_environ = self._make_extra_environ(username='harp4162')
        res = self.testapp.get(
            enrollment_assignments, extra_environ=instructor_environ)
        assg = res.json_body['Items'][self.lesson_page_id][0]

        assg_href = assg.get('href')
        assert_that(assg_href, not_none())
        for part in assg['parts']:
            question_set = part['question_set']
            for question in question_set['questions']:
                for qpart in question['parts']:
                    assert_that(qpart, has_entries('solutions', not_none(),
                                                   'explanation', not_none()))

        # If we submit...
        from nti.assessment.submission import QuestionSubmission
        question_id = u"tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.qid.aristotle.1"
        qs_submission = QuestionSetSubmission(questionSetId=self.question_set_id,
                                              questions=(QuestionSubmission(questionId=question_id, parts=[0]),))
        submission = AssignmentSubmission(assignmentId=self.assignment_id,
                                          parts=(qs_submission,))

        ext_obj = to_external_object(submission)
        # Need to start
        assignment_res = self.testapp.get(assg_href)
        start_href = self.require_link_href_with_rel(assignment_res.json_body,
                                                     'Commence')
        self.testapp.post(start_href)
        res = self.testapp.post_json(assg_href, ext_obj)

        def _check_pending(pending):
            for assessed_qset in pending['parts']:
                for question in assessed_qset['questions']:
                    for qpart in question['parts']:
                        assert_that(qpart, has_entries('solutions', None,
                                                       'explanation', None))

        _check_pending(res.json_body)
        # ... and get history
        history_res = self._check_submission(res, enrollment_history_link)

        # ... the assessed parts are also stripped
        history_item = next(iter(history_res.json_body['Items'].values()))
        history_item = next(iter(history_item['Items']))

        pending = history_item['pendingAssessment']
        _check_pending(pending)

        with mock_dataserver.mock_db_trans(self.ds, site_name='janux.ou.edu'):
            course = ICourseInstance(find_object_with_ntiid(COURSE_NTIID))
            histories = IUsersCourseAssignmentHistories(course)
            user_container = histories.get(self.default_username)
            submission_container = user_container.get(self.assignment_id)
            assert_that(submission_container, has_length(1))
            item = submission_container.values()[0]
            assignment = item.Assignment
            assert_that(assignment, not_none())
            assert_that(assignment.ntiid, is_(self.assignment_id))
            histories.clear()
            assert_that(histories, has_length(0))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_ipad_hack(self):

        # First, adjust the parts and category
        with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
            assignment = component.getUtility(IQAssignment, self.assignment_id)
            assignment._old_parts = assignment.parts
            old_cat = assignment.category_name

            assignment.category_name = IPlainTextContentFragment(u'no_submit')
            assignment.parts = ()

        try:
            # Make sure we're enrolled
            res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                         COURSE_NTIID,
                                         status=201)

            course_res = self.testapp.get(COURSE_URL).json_body
            enrollment_assignments = self.require_link_href_with_rel(course_res,
                                                                     'AssignmentsByOutlineNode')
            self.require_link_href_with_rel(course_res,
                                            'AssignmentsByOutlineNode')

            res = self.testapp.get(enrollment_assignments,
                                   extra_environ={'HTTP_USER_AGENT': "NTIFoundation DataLoader NextThought/1.1.1/38605 (x86_64; 7.1)"})
            assert_that(res.json_body, has_entry(self.lesson_page_id,
                                                 contains(has_entries('Class', 'Assignment',
                                                                      'NTIID', self.assignment_id,
                                                                      'parts', [
                                                                          {'Class': 'AssignmentPart'}
                                                                       ],
                                                                      'category_name', 'no_submit'))))

            res = self.testapp.get(enrollment_assignments)
            assert_that(res.json_body['Items'], has_entry(self.lesson_page_id,
                                                          contains(has_entries('Class', 'Assignment',
                                                                               'NTIID', self.assignment_id,
                                                                               'parts', is_empty(),
                                                                               'category_name', 'no_submit'))))

        finally:
            with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
                assignment = component.getUtility(IQAssignment, self.assignment_id)
                assignment.category_name = old_cat
                assignment.parts = assignment._old_parts
                del assignment._old_parts


class TestAssignmentFiltering(RegisterAssignmentLayerMixin, ApplicationLayerTest):

    layer = RegisterAssignmentLayer
    default_origin = 'http://janux.ou.edu'
    # With the feature missing

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_assignment_items_view_links_in_enrollments(self):

        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)

        enrollment_oid = res.json_body['NTIID']

        course_res = self.testapp.get(COURSE_URL).json_body
        links_from = course_res
        enrollment_assignments = self.require_link_href_with_rel(links_from,
                                                                 'AssignmentsByOutlineNode')
        enrollment_non_assignments = self.require_link_href_with_rel(links_from,
                                                                     'NonAssignmentAssessmentItemsByOutlineNode')

        course_href = course_res['href']
        if course_href[-1] != '/':
            course_href += '/'
        course_href = urllib_parse.unquote(course_href)

        # It's also not on the page info, and the question sets it contains
        # aren't either
        lesson_page_id = "tag:nextthought.com,2011-10:OU-HTML-CLC3403_LawAndJustice.sec:QUIZ_01.01"
        question_set_id = "tag:nextthought.com,2011-10:OU-NAQ-CLC3403_LawAndJustice.naq.set.qset:QUIZ1_aristotle"
        page_info_mt = nti_mimetype_with_class('pageinfo')

        def _missing():
            res = self.testapp.get(enrollment_assignments)
            assert_that(res.json_body,
                        has_entry(u'href', course_href + '@@AssignmentsByOutlineNode'))

            res = self.fetch_by_ntiid(lesson_page_id,
                                      headers={'Accept': str(page_info_mt)})
            items = res.json_body.get('AssessmentItems', ())
            assert_that(items,
                        does_not(contains(has_entry('Class', 'Assignment'))))
            assert_that(items,
                        does_not(contains(has_entry('NTIID', question_set_id))))

            # Nor are they in the non-assignment-items
            res = self.testapp.get(enrollment_non_assignments)
            assert_that(res.json_body,
                        has_entries('href', course_href + '@@NonAssignmentAssessmentItemsByOutlineNode'))
            assert_that(res.json_body['Items'],
                        is_not(has_item(lesson_page_id)))

        _missing()

        # Now pretend to be enrolled for credit
        with mock_dataserver.mock_db_trans(self.ds):
            from nti.ntiids import ntiids
            record = ntiids.find_object_with_ntiid(enrollment_oid)
            record.Scope = 'ForCredit'

        res = self.testapp.get(enrollment_assignments)
        assert_that(res.json_body['Items'], has_entry(self.lesson_page_id,
                                                      contains(has_entries('Class', 'Assignment',
                                                                           'NTIID', self.assignment_ntiid))))

        # the question sets are still not actually available because they are
        # in the assignment
        res = self.testapp.get(enrollment_non_assignments)
        assert_that(res.json_body,
                    has_entries('href', course_href + '@@NonAssignmentAssessmentItemsByOutlineNode'))
        assert_that(res.json_body['Items'],
                    is_not(has_item(lesson_page_id)))

        ntiid_set = set()
        found_survey = False
        found_assignment = False

        # When we get the page info, only the assignment comes back,
        # not the things it contains
        res = self.fetch_by_ntiid(lesson_page_id,
                                  headers={'Accept': str(page_info_mt)})
        items = res.json_body.get('AssessmentItems', ())
        for item in items:
            ntiid_set.add(item.get('NTIID'))
            found_survey = found_survey or item.get('Class') == 'Survey'
            found_assignment = found_assignment \
                            or item.get('Class') == 'Assignment'
        assert_that(found_survey, is_(True))
        assert_that(found_assignment, is_(True))

        assert_that(ntiid_set,
                    does_not(contains(question_set_id)))

        # If, however, we set the assignment policy to exclude, it's not
        # present again
        with mock_dataserver.mock_db_trans(site_name='platform.ou.edu'):
            cat = component.getUtility(ICourseCatalog)
            clc_entries = [x for x in cat.iterCatalogEntries()
                           if x.ProviderUniqueID == 'CLC 3403']
            assert_that(clc_entries, has_length(1))
            course = ICourseInstance(clc_entries[0])
            policies = IQAssignmentPolicies(course)
            policies[self.assignment_ntiid] = {'excluded': True}

        _missing()
