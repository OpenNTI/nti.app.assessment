#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import contains
from hamcrest import assert_that
from hamcrest import greater_than
from hamcrest import has_property
from hamcrest import same_instance

from nti.testing.matchers import validly_provides

from nti.testing.time import time_monotonically_increases

import unittest

from nti.app.assessment import history
from nti.app.assessment import feedback
from nti.app.assessment import interfaces

from nti.app.assessment.tests import AssessmentLayerTest


class TestFeedback(unittest.TestCase):

    def test_interfaces(self):
        item = feedback.UsersCourseAssignmentHistoryItemFeedback()
        item.creator = u'foo'  # anything is accepted eventually
        assert_that(item,
                    validly_provides(interfaces.IUsersCourseAssignmentHistoryItemFeedback))

        assert_that(feedback.UsersCourseAssignmentHistoryItemFeedbackContainer(),
                    validly_provides(interfaces.IUsersCourseAssignmentHistoryItemFeedbackContainer))

    def test_inserting_deleting(self):
        container = feedback.UsersCourseAssignmentHistoryItemFeedbackContainer()
        for _ in range(25):
            container['ignored'] = feedback.UsersCourseAssignmentHistoryItemFeedback()

        assert_that(container.keys(),
                    contains(*[str(i) for i in range(25)]))

        # Once we had a problem where if we deleted an item and then added
        # another item, we would get a key conflict
        del container['0']
        del container['15']

        item = feedback.UsersCourseAssignmentHistoryItemFeedback()
        container['ignored'] = item
        # last key,
        assert_that(container['25'], is_(same_instance(item)))
        # and still last value
        assert_that(container.Items[-1], is_(same_instance(item)))

        # Same for in the middle
        item = feedback.UsersCourseAssignmentHistoryItemFeedback()
        container['ignored'] = item
        # last key,
        assert_that(container['26'], is_(same_instance(item)))
        # but still last value
        assert_that(container.Items[-1], is_(same_instance(item)))


from zope import lifecycleevent


class TestFunctionalFeedback(AssessmentLayerTest):

    @time_monotonically_increases
    def test_adding_feedback_changes_item_last_modified(self):
        history_item = history.UsersCourseAssignmentHistoryItem()
        container = history_item.Feedback
        history_lm = history_item.lastModified

        container['ignored'] = feedback.UsersCourseAssignmentHistoryItemFeedback()

        assert_that(history_item, has_property('lastModified',
                                               greater_than(history_lm)))

    @time_monotonically_increases
    def test_deleting_feedback_changes_item_last_modified(self):
        history_item = history.UsersCourseAssignmentHistoryItem()
        container = history_item.Feedback

        container['ignored'] = feedback.UsersCourseAssignmentHistoryItemFeedback()
        history_lm = history_item.lastModified

        del container['0']

        assert_that(history_item, has_property('lastModified',
                                               greater_than(history_lm)))

    @time_monotonically_increases
    def test_editing_feedback_changes_item_last_modified(self):
        history_item = history.UsersCourseAssignmentHistoryItem()
        container = history_item.Feedback

        container['ignored'] = feedback.UsersCourseAssignmentHistoryItemFeedback()
        history_lm = history_item.lastModified

        lifecycleevent.modified(container['0'])
        assert_that(history_item, has_property('lastModified',
                                               greater_than(history_lm)))
