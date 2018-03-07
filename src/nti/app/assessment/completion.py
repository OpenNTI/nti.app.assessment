#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Adapters for application-level events.

.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.completion.interfaces import IProgress
from nti.contenttypes.completion.interfaces import ICompletableItemCompletionPolicy
from nti.contenttypes.completion.interfaces import ICompletionContextCompletionPolicyContainer

from nti.contenttypes.completion.progress import Progress

from nti.dataserver.interfaces import IUser

logger = __import__('logging').getLogger(__name__)


class _DefaultSubmissionCompletionPolicy(object):
    """
    A simple completion policy that only cares about submissions for completion.
    """

    def __init__(self, obj):
        self.assessment = obj

    def is_complete(self, progress):
        return progress is not None and progress.HasProgress


@component.adapter(IQAssignment)
@interface.implementer(ICompletableItemCompletionPolicy)
class DefaultAssignmentCompletionPolicy(_DefaultSubmissionCompletionPolicy):
    pass


@component.adapter(IQuestionSet)
@interface.implementer(ICompletableItemCompletionPolicy)
class DefaultSelfAssessmentCompletionPolicy(_DefaultSubmissionCompletionPolicy):
    pass


def _assessment_completion_policy(assessment, course):
    """
    Fetch the :class:`ICompletableItemCompletionPolicy` for this assessment, course.
    """
    # First see if we have a specific policy set on our context.
    context_policies = ICompletionContextCompletionPolicyContainer(course)
    try:
        result = context_policies[assessment.ntiid]
    except KeyError:
        # Ok, fetch the default
        result = ICompletableItemCompletionPolicy(assessment)
    return result


@component.adapter(IQAssignment, ICourseInstance)
@interface.implementer(ICompletableItemCompletionPolicy)
def _assignment_completion_policy(assignment, course):
    return _assessment_completion_policy(assignment, course)


@component.adapter(IQuestionSet, ICourseInstance)
@interface.implementer(ICompletableItemCompletionPolicy)
def _self_assessment_completion_policy(question_set, course):
    return _assessment_completion_policy(question_set, course)


@component.adapter(IUser, IQuestionSet, ICourseInstance)
@interface.implementer(IProgress)
def _self_assessment_progress(user, question_set, unused_course):
    """
    Fetch the :class:`IProgress` for this user, question_set, course.

    Note: we're not using the course yet, but we could via the
    :class:`IContainerContext`.
    """
    items = user.getContainer(question_set.containerId)
    submitted = False
    submitted_date = None
    if items is not None:
        submitted = bool(len(items))
        # First submission date
        submitted_date = submitted and items.values()[0].createdTime
    # What would we possibly want to do here besides return True/False if we
    # have a submission.
    progress = Progress(NTIID=question_set.ntiid,
                        AbsoluteProgress=None,
                        MaxPossibleProgress=None,
                        LastModified=submitted_date,
                        HasProgress=submitted)
    return progress
