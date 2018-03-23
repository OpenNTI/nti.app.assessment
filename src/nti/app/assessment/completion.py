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

from nti.contenttypes.completion.completion import CompletedItem

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.completion.interfaces import IProgress
from nti.contenttypes.completion.interfaces import IRequiredCompletableItemProvider
from nti.contenttypes.completion.interfaces import ICompletableItemCompletionPolicy
from nti.contenttypes.completion.interfaces import ICompletionContextCompletionPolicyContainer

from nti.contenttypes.completion.progress import Progress

from nti.contenttypes.completion.utils import is_item_required

from nti.dataserver.interfaces import IUser

logger = __import__('logging').getLogger(__name__)


class _DefaultSubmissionCompletionPolicy(object):
    """
    A simple completion policy that only cares about submissions for completion.
    """

    def __init__(self, obj):
        self.assessment = obj

    def is_complete(self, progress):
        result = None
        if progress is not None and progress.HasProgress:
            result = CompletedItem(Item=progress.Item,
                                   Principal=progress.User,
                                   CompletedDate=progress.LastModified)
        return result


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
def _self_assessment_progress(user, question_set, course):
    """
    Fetch the :class:`IProgress` for this user, question_set, course.

    Note: we're not using the course yet, but we could via the
    :class:`IContainerContext`.
    """
    items = user.getContainer(question_set.containerId)
    progress = None
    if items:
        # First submission date
        submitted_date = items.values()[0].createdTime
        # What would we possibly want to do here besides return True/False if
        # we have a submission?
        progress = Progress(NTIID=question_set.ntiid,
                            AbsoluteProgress=None,
                            MaxPossibleProgress=None,
                            LastModified=submitted_date,
                            User=user,
                            Item=question_set,
                            CompletionContext=course,
                            HasProgress=True)
    return progress


@component.adapter(IUser, ICourseInstance)
@interface.implementer(IRequiredCompletableItemProvider)
class _AssessmentItemProvider(object):
    """
    Return the :class:`ICompletableItem` items for this user/course.
    """

    def __init__(self, user, course):
        self.user = user
        self.course = course

    def iter_items(self):
        catalog = ICourseAssignmentCatalog(self.course)
        uber_filter = get_course_assessment_predicate_for_user(self.user,
                                                               self.course)
        # Must grab all assignments in our parent
        assignments = catalog.iter_assignments(course_lineage=True)
        return (x for x in assignments
                if uber_filter(x) and is_item_required(x, self.course))
