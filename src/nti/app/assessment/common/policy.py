#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from requests.structures import CaseInsensitiveDict

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.submissions import has_submissions

from nti.app.assessment.common.utils import get_policy_field

from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer

from nti.app.externalization.error import raise_json_error

from nti.assessment.common import can_be_auto_graded

from nti.assessment.interfaces import IQAssessmentPolicies

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import StandardExternalFields

from nti.links.links import Link

from nti.traversal.traversal import find_interface

CLASS = StandardExternalFields.CLASS
LINKS = StandardExternalFields.LINKS
MIME_TYPE = StandardExternalFields.MIMETYPE

UNGRADABLE_CODE = 'UngradableInAutoGradeAssignment'
UNGRADABLE_MSG = _(u"Ungradable item in auto-graded assignment.")

DISABLE_AUTO_GRADE_MSG = _(
    u"Removing points to auto-gradable assignment. Do you want to disable auto-grading?"
)

AUTO_GRADE_NO_POINTS_MSG = _(
    u"Cannot enable auto-grading without setting a point value."
)

logger = __import__('logging').getLogger(__name__)


def get_policy_for_assessment(asm_id, context):
    course = ICourseInstance(context)
    policies = IQAssessmentPolicies(course)
    # pylint: disable=too-many-function-args
    policy = policies.getPolicyForAssessment(asm_id)
    return policy


def get_auto_grade_policy(assignment, course):
    """
    For a given assignment (or ntiid), return the `auto_grade` policy for the given course.
    """
    return get_policy_field(assignment, course, 'auto_grade')


def get_policy_locked(assignment, course):
    """
    For a given assignment (or ntiid), return the policy `locked` state for the given
    course.
    """
    return get_policy_field(assignment, course, 'locked')


def get_policy_excluded(assignment, course):
    """
    For a given assignment (or ntiid), return the policy `excluded` state for the given
    course.
    """
    return get_policy_field(assignment, course, 'excluded')


def get_auto_grade_policy_state(assignment, course):
    """
    For a given assignment (or ntiid), return the autograde state for the given course.
    """
    policy = get_auto_grade_policy(assignment, course)
    result = False
    if policy and policy.get('disable') is not None:
        # Only allow auto_grading if disable is explicitly set to False.
        result = not policy.get('disable')
    return result


def get_submission_buffer_policy(assignment, course):
    """
    For a given assignment (or ntiid), return the 'submission_buffer' policy
    for the given course.

    The submission buffer is the number of seconds an assignment may be
    submitted past its due-date, beyond which time submissions should be
    prevented.
    """
    return get_policy_field(assignment, course, 'submission_buffer')


def validate_auto_grade(assignment, course, request=None, challenge=False, raise_exc=True, method='POST'):
    """
    Validate the assignment has the proper state for auto-grading, if
    necessary. If not raising/challenging, returns a bool indicating
    whether this assignment is auto-gradable.
    """
    auto_grade = get_auto_grade_policy_state(assignment, course)
    valid_auto_grade = True
    if auto_grade:
        # Work to do
        valid_auto_grade = can_be_auto_graded(assignment)
        if not valid_auto_grade and raise_exc:
            # Probably toggling auto_grade on assignment with essays (e.g).
            if not challenge:
                request = request or get_current_request()
                raise_json_error(request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                     'message': UNGRADABLE_MSG,
                                     'code': UNGRADABLE_CODE,
                                 },
                                 None)
            # No, so inserting essay (e.g.) into autogradable.
            links = (
                Link(request.path, rel='confirm',
                     params={'overrideAutoGrade': True},
                     method=method),
            )
            raise_json_error(request,
                             hexc.HTTPConflict,
                             {
                                 CLASS: 'DestructiveChallenge',
                                 'message': UNGRADABLE_MSG,
                                 'code': UNGRADABLE_CODE,
                                 LINKS: to_external_object(links),
                                 MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
                             },
                             None)
    return valid_auto_grade


def validate_auto_grade_points(assignment, course, request, externalValue):
    """
    Validate the assignment has the proper state with auto_grading and
    total_points. If removing points from auto-gradable, we challenge the
    user, disabling auto_grade upon override. If setting auto_grade without
    points, we 422.
    """
    auto_grade = get_auto_grade_policy_state(assignment, course)
    if auto_grade:
        auto_grade_policy = get_auto_grade_policy(assignment, course)
        total_points = auto_grade_policy.get('total_points')
        params = CaseInsensitiveDict(request.params)
        # Removing points while auto_grade on; challenge.
        if not total_points and 'total_points' in externalValue:
            if not params.get('disableAutoGrade'):
                links = (
                    Link(request.path, rel='confirm',
                         params={'disableAutoGrade': True}, method='PUT'),
                )
                raise_json_error(request,
                                 hexc.HTTPConflict,
                                 {
                                     CLASS: 'DestructiveChallenge',
                                     'message': DISABLE_AUTO_GRADE_MSG,
                                     'code': 'RemovingAutoGradePoints',
                                     LINKS: to_external_object(links),
                                     MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
                                 },
                                 None)
            # Disable auto grade
            auto_grade_policy['disable'] = True
        # Trying to enable auto_grade without points; 422.
        if not total_points and 'auto_grade' in externalValue:
            raise_json_error(request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': AUTO_GRADE_NO_POINTS_MSG,
                                 'code': 'AutoGradeWithoutPoints',
                             },
                             None)


def pre_validate_question_change(question, externalValue):
    """
    Validate the proposed changes with the current question state
    (before modification), returning the parts that changed.
    """
    parts = externalValue.get('parts')
    check_solutions = not IQAvoidSolutionCheck.providedBy(question)
    course = find_interface(question, ICourseInstance, strict=False)
    regrade_parts = []
    if parts and has_submissions(question, course):
        for part, change in zip(question.parts, parts):
            analyzer = IQPartChangeAnalyzer(part, None)
            if analyzer is not None:
                # pylint: disable=too-many-function-args
                if not analyzer.allow(change, check_solutions):
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': _(u"Question has submissions. It cannot be updated."),
                                         'code': 'CannotChangeObjectDefinition',
                                     },
                                     None)
                if analyzer.regrade(change):
                    regrade_parts.append(part)
    return regrade_parts
