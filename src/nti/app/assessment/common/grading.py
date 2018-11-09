#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope.event import notify

from nti.app.assessment.common.assessed import reassess_assignment_history_item

from nti.app.assessment.common.policy import get_policy_submission_priority

from nti.app.assessment.common.submissions import evaluation_submissions

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.interfaces import ObjectRegradeEvent

logger = __import__('logging').getLogger(__name__)


def regrade_evaluation(context, course):
    result = []
    submissions = evaluation_submissions(context, course)
    # For multiple submissions, we want to make sure we re-grade in the order
    # of submission so that we store the grade appropriately (most_recent vs
    # highest_grade).
    if get_policy_submission_priority(context, course) == 'most_recent':
        submissions = sorted(submissions, key=lambda x: x.createdTime)
    for item in submissions:
        if IUsersCourseAssignmentHistoryItem.providedBy(item):
            logger.info('Regrading (%s) (user=%s)',
                        item.Submission.assignmentId, item.creator)
            result.append(item)
            reassess_assignment_history_item(item)
            # Now broadcast we need a new grade
            notify(ObjectRegradeEvent(item))
    return result
