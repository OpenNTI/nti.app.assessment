#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import INotableFilter


@interface.implementer(INotableFilter)
class AssignmentFeedbackNotableFilter(object):
    """
    Determines if assignment feedback is notable for the given user.
    Feedback is notable if it is on our user's assignments and the feedback
    is not created by our user.

    Typically, students get feedback objects from another notable filter.
    This also provides instructors with feedback notables on course
    assessments..
    """

    def __init__(self, context):
        self.context = context

    def is_notable(self, obj, user):
        result = False
        if IUsersCourseAssignmentHistoryItemFeedback.providedBy(obj):
            history_item = obj.__parent__.__parent__
            submission = history_item.Submission
            course = ICourseInstance(self.context)
            instructors = course.instructors or ()
            result =     (submission.creator == user or user in instructors) \
                     and obj.creator != user
        return result
