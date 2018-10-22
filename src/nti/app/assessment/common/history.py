#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component

from nti.app.assessment.common.evaluations import get_evaluation_courses

from nti.app.assessment.common.utils import get_courses
from nti.app.assessment.common.utils import to_course_list

from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contenttypes.courses.interfaces import ICourseInstance

logger = __import__('logging').getLogger(__name__)


def get_most_recent_history_item(user, course, assignment):
    """
    For bwc, it's necessary to get a single submission rather than one or
    more possible submissions.
    """
    result = None
    assignment_ntiid = getattr(assignment, 'ntiid', assignment)
    container = component.queryMultiAdapter((course, user),
                                            IUsersCourseAssignmentHistory)
    if container is not None:
        submission_container = container.get(assignment_ntiid)
        if submission_container:
            result = tuple(submission_container.values())[-1]
    return result


def get_user_submission_count(user, course, assignment):
    """
    Return the submission count for a user, course and assignment_ntiid.
    """
    result = 0
    assignment_ntiid = getattr(assignment, 'ntiid', assignment)
    container = component.queryMultiAdapter((course, user),
                                            IUsersCourseAssignmentHistory)
    if container is not None:
        submission_container = container.get(assignment_ntiid)
        if submission_container:
            result = len(submission_container)
    return result


def get_assessment_metadata_item(context, user, assignment):
    course = ICourseInstance(context, None)
    metadata = component.queryMultiAdapter((course, user),
                                           IUsersCourseAssignmentMetadata)
    if metadata is not None:
        if IQAssignment.providedBy(assignment):
            ntiid = assignment.ntiid
        else:
            ntiid = str(assignment)
        if ntiid in metadata:
            return metadata[ntiid]
    return None


def delete_context_contained_data(container_iface, context, course, subinstances=True):
    result = 0
    course = ICourseInstance(course)
    context_ntiid = getattr(context, 'ntiid', context)
    for course in get_courses(course, subinstances=subinstances):
        container = container_iface(course, None) or {}
        for user_data in list(container.values()):  # snapshot
            if context_ntiid in user_data:
                del user_data[context_ntiid]
                result += 1
    return result


def delete_evaluation_submissions(context, course, subinstances=True):
    result = delete_context_contained_data(IUsersCourseAssignmentHistories,
                                           context,
                                           course,
                                           subinstances)
    return result


def delete_inquiry_submissions(context, course, subinstances=True):
    result = delete_context_contained_data(IUsersCourseInquiries,
                                           context,
                                           course,
                                           subinstances)
    return result


def has_savepoints(context, courses=()):
    context_ntiid = getattr(context, 'ntiid', context)
    for course in to_course_list(courses) or ():
        savepoints = IUsersCourseAssignmentSavepoints(course, None)
        # pylint: disable=too-many-function-args
        if savepoints is not None and savepoints.has_assignment(context_ntiid):
            return True
    return False


def delete_evaluation_savepoints(context, course, subinstances=True):
    result = delete_context_contained_data(IUsersCourseAssignmentSavepoints,
                                           context,
                                           course,
                                           subinstances)
    return result


def delete_evaluation_metadata(context, course, subinstances=True):
    result = delete_context_contained_data(IUsersCourseAssignmentMetadataContainer,
                                           context,
                                           course,
                                           subinstances)
    return result


def delete_evaluation_policies(context, course, subinstances=True):
    result = 0
    course = ICourseInstance(course)
    context_ntiid = getattr(context, 'ntiid', context)
    for course in get_courses(course, subinstances=subinstances):
        for provided in (IQAssessmentPolicies, IQAssessmentDateContext):
            container = provided(course, None) or {}
            try:
                del container[context_ntiid]
                result += 1
            except KeyError:
                pass
    return result


def delete_all_evaluation_policy_data(evaluation):
    for course in get_evaluation_courses(evaluation):
        delete_evaluation_policies(evaluation, course)


def delete_all_evaluation_data(evaluation):
    for course in get_evaluation_courses(evaluation):
        # delete policy data
        delete_evaluation_policies(evaluation, course)
        # delete submission data
        if IQInquiry.providedBy(evaluation):
            delete_inquiry_submissions(evaluation, course)
        else:
            delete_evaluation_metadata(evaluation, course)
            delete_evaluation_savepoints(evaluation, course)
            delete_evaluation_submissions(evaluation, course)
