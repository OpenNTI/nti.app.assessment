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

from nti.app.assessment.interfaces import IUsersCourseInquiry

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.contenttypes.completion.completion import CompletedItem
from nti.contenttypes.completion.policies import AbstractCompletableItemCompletionPolicy

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.completion.interfaces import IProgress
from nti.contenttypes.completion.interfaces import ICompletableItemProvider
from nti.contenttypes.completion.interfaces import IRequiredCompletableItemProvider
from nti.contenttypes.completion.interfaces import ICompletableItemCompletionPolicy
from nti.contenttypes.completion.interfaces import ICompletionContextCompletionPolicyContainer

from nti.contenttypes.completion.progress import Progress

from nti.contenttypes.completion.utils import is_item_required

from nti.contenttypes.courses.utils import get_enrollment_record

from nti.dataserver.interfaces import IUser

from nti.externalization.proxy import removeAllProxies

from nti.externalization.persistence import NoPickle
from nti.app.assessment.common.policy import get_policy_completion_passing_percent

logger = __import__('logging').getLogger(__name__)


@NoPickle
class _DefaultSubmissionCompletionPolicy(AbstractCompletableItemCompletionPolicy):
    """
    A simple completion policy that only cares about submissions for completion.
    For assignment, success is driven by the policy `completion_passing_percent`.
    """

    def __init__(self, obj):
        self.assessment = obj

    def is_complete(self, progress):
        result = None
        if progress is not None and progress.HasProgress:
            result = CompletedItem(Item=progress.Item,
                                   Principal=progress.User,
                                   CompletedDate=progress.LastModified)
            completion_passing_percent = get_policy_completion_passing_percent(self.assessment,
                                                                               self._v_course_context)
            if completion_passing_percent:
                result.Success = bool(    progress.PercentageProgress \
                                      and progress.PercentageProgress >= completion_passing_percent)
        return result


@component.adapter(IQAssignment)
@interface.implementer(ICompletableItemCompletionPolicy)
class DefaultAssignmentCompletionPolicy(_DefaultSubmissionCompletionPolicy):
    pass


@component.adapter(IQuestionSet)
@interface.implementer(ICompletableItemCompletionPolicy)
class DefaultSelfAssessmentCompletionPolicy(_DefaultSubmissionCompletionPolicy):
    pass


@component.adapter(IQSurvey)
@interface.implementer(ICompletableItemCompletionPolicy)
class DefaultSurveyCompletionPolicy(_DefaultSubmissionCompletionPolicy):
    pass


def _assessment_completion_policy(assessment, course):
    """
    Fetch the :class:`ICompletableItemCompletionPolicy` for this assessment
    and course.
    """
    # First see if we have a specific policy set on our context.
    context_policies = ICompletionContextCompletionPolicyContainer(course)
    try:
        result = context_policies[assessment.ntiid]
    except KeyError:
        # Ok, fetch the default
        result = ICompletableItemCompletionPolicy(assessment)
    result._v_course_context = course
    return result


@component.adapter(IQAssignment, ICourseInstance)
@interface.implementer(ICompletableItemCompletionPolicy)
def _assignment_completion_policy(assignment, course):
    return _assessment_completion_policy(assignment, course)


@component.adapter(IQuestionSet, ICourseInstance)
@interface.implementer(ICompletableItemCompletionPolicy)
def _self_assessment_completion_policy(question_set, course):
    return _assessment_completion_policy(question_set, course)


@component.adapter(IQSurvey, ICourseInstance)
@interface.implementer(ICompletableItemCompletionPolicy)
def _survey_completion_policy(question_set, course):
    return _assessment_completion_policy(question_set, course)


@component.adapter(IUser, IQuestionSet, ICourseInstance)
@interface.implementer(IProgress)
def _self_assessment_progress(user, question_set, course):
    """
    Fetch the :class:`IProgress` for this user, question_set, course.
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


@component.adapter(IUser, IQSurvey, ICourseInstance)
@interface.implementer(IProgress)
def _survey_progress(user, survey, course):
    """
    Fetch the :class:`IProgress` for this user, survey, course.
    """
    progress = None
    histories = component.getMultiAdapter((course, user),
                                          IUsersCourseInquiry)
    submission = histories.get(survey.ntiid)
    if submission:
        # What would we possibly want to do here besides return True/False if
        # we have a submission?
        progress = Progress(NTIID=survey.ntiid,
                            AbsoluteProgress=None,
                            MaxPossibleProgress=None,
                            LastModified=submission.created,
                            User=user,
                            Item=survey,
                            CompletionContext=course,
                            HasProgress=True)
    return progress


@component.adapter(ICourseInstance)
@interface.implementer(ICompletableItemProvider)
class _AssessmentItemProvider(object):
    """
    Return the :class:`ICompletableItem` items for this user/course.
    """

    def __init__(self, course):
        self.course = course
        self._scope_to_items = dict()

    def _include_item(self, unused_item):
        return True

    def iter_items(self, user):
        record = get_enrollment_record(self.course, user)
        scope = record.Scope if record is not None else 'ALL'
        result = self._scope_to_items.get(scope)
        if result is None:
            catalog = ICourseAssignmentCatalog(self.course)
            uber_filter = get_course_assessment_predicate_for_user(user,
                                                                   self.course)
            # Must grab all assignments in our parent
            # pylint: disable=too-many-function-args
            assignments = catalog.iter_assignments(True)
            result = [removeAllProxies(x) for x in assignments
                      if uber_filter(x) and self._include_item(x)]
            self._scope_to_items[scope] = result
        return result


@component.adapter(ICourseInstance)
@interface.implementer(IRequiredCompletableItemProvider)
class _AssessmentRequiredItemProvider(_AssessmentItemProvider):
    """
    Return the required :class:`ICompletableItem` items for this user/course.
    """

    def _include_item(self, item):
        return is_item_required(item, self.course)
