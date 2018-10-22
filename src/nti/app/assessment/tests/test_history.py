#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_length
from hamcrest import has_entries
from hamcrest import assert_that
from hamcrest import has_property

from nti.testing.matchers import is_false
from nti.testing.matchers import validly_provides

import weakref

from nti.app.assessment.history import UsersCourseAssignmentHistory
from nti.app.assessment.history import UsersCourseAssignmentHistories
from nti.app.assessment.history import UsersCourseAssignmentHistoryItem
from nti.app.assessment.history import UsersCourseAssignmentHistoryItemContainer

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemSummary
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemContainer

from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment

from nti.assessment.submission import AssignmentSubmission

from nti.dataserver.interfaces import IUser

from nti.dataserver.users.users import User

from nti.app.assessment.tests import AssessmentLayerTest

from nti.externalization.tests import externalizes


class TestHistory(AssessmentLayerTest):

    # NOTE: We don't actually need all this setup the layer does,
    # but it saves time when we run in bulk

    def test_provides(self):
        histories = UsersCourseAssignmentHistories()
        history = UsersCourseAssignmentHistory()
        history.__parent__ = histories
        # Set an owner; use a python wref instead of the default
        # adapter to wref as it requires an intid utility
        history.owner = weakref.ref(User(u'sjohnson@nextthought.com'))

        submission_container = UsersCourseAssignmentHistoryItemContainer()
        submission_container.__parent__ = history

        item = UsersCourseAssignmentHistoryItem()
        item.creator = u'foo'
        item.__parent__ = submission_container
        assert_that(item,
                    validly_provides(IUsersCourseAssignmentHistoryItem))

        assert_that(history,
                    validly_provides(IUsersCourseAssignmentHistory))

        assert_that(submission_container,
                    validly_provides(IUsersCourseAssignmentHistoryItemContainer))

        user = IUser(item, None)
        if user is not None:
            assert_that(user, is_(history.owner))

        user = IUser(history, None)
        if user is not None:
            assert_that(user, is_(history.owner))

        summ = IUsersCourseAssignmentHistoryItemSummary(item)
        assert_that(summ,
                    validly_provides(IUsersCourseAssignmentHistoryItemSummary))

        assert_that(item,
				    externalizes(has_entries('Class', 'UsersCourseAssignmentHistoryItem',
                                             'MimeType', 'application/vnd.nextthought.assessment.userscourseassignmenthistoryitem')))

    def test_record(self):
        history = UsersCourseAssignmentHistory()
        submission = AssignmentSubmission(assignmentId=u'b')
        pending = QAssignmentSubmissionPendingAssessment(assignmentId=u'b',
														 parts=())

        item = history.recordSubmission(submission, pending)
        # Container validation
        submission_container = item.__parent__
        assert_that(submission_container, has_length(1))
        assert_that(submission_container,
                    has_property('__name__', is_(submission.assignmentId)))

        assert_that(item, has_property('Submission', is_(submission)))
        assert_that(item,
					has_property('__name__', is_(u'UsersCourseAssignmentHistoryItem')))

        assert_that(item.__parent__, is_(submission_container))

        # Second submission
        submission2 = AssignmentSubmission(assignmentId=u'b')
        pending2 = QAssignmentSubmissionPendingAssessment(assignmentId=u'b',
                                                          parts=())
        item2 = history.recordSubmission(submission2, pending2)
        # Container validation
        submission_container = item2.__parent__
        assert_that(submission_container, has_length(2))
        assert_that(submission_container,
                    has_property('__name__', is_(submission.assignmentId)))

        assert_that(item2, has_property('Submission', is_(submission2)))
        assert_that(item2,
                    has_property('__name__', is_not(u'UsersCourseAssignmentHistoryItem')))

        assert_that(item2.__parent__, is_(submission_container))

        assert_that(history, has_property('lastViewed', 0))

    def test_nuclear_option(self):
        history = UsersCourseAssignmentHistory()
        submission = AssignmentSubmission(assignmentId=u'b')
        pending = QAssignmentSubmissionPendingAssessment(assignmentId=u'b',
														 parts=())

        item = history.recordSubmission(submission, pending)

        # in the absence of info, it's false
        assert_that(item,
					has_property('_student_nuclear_reset_capable', is_false()))
