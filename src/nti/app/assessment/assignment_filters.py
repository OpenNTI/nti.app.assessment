#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Filters for assignment visibility.

.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from nti.assessment.interfaces import IQAssessmentPolicies

from nti.contenttypes.courses.interfaces import ES_PUBLIC
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseAssessmentUserFilter

from nti.contenttypes.courses.utils import get_enrollment_in_hierarchy
from nti.contenttypes.courses.utils import is_instructed_or_edited_by_name

from nti.dataserver.interfaces import IUser

logger = __import__('logging').getLogger(__name__)


# ACLs
# Notice that everything based on enrollment *could* be done
# with an ACL. Likewise, everything done with closed enrollment
# could also be done with an ACL. That's probably a better, more
# general approach.
#
# However, the difficulty is in establishing the ACL. It's not clear
# to me when the best time is to do that. It can't be done when they
# are read from the file because the course they belong to may not
# be available. We could calculate it dynamically with an IACLProvider,
# but that bakes in a lot of knowledge about the LegacyCourseInstance
# structure currently, and I'd like to avoid spreading that.
# So for now, we're implementing the filters with brute force


@component.adapter(IUser, ICourseInstance)
@interface.implementer(ICourseAssessmentUserFilter)
class UserEnrolledForCreditInCourseOrInstructsFilter(object):
    """
    Allows access to the assignment if the user is enrolled
    for credit, or if the assignment designates that it is available
    to everyone.
    """

    TEST_OVERRIDE = False

    def __init__(self, user, course):
        self.user = user
        self.course = course

    @Lazy
    def is_instructor(self):
        return is_instructed_or_edited_by_name(self.course, self.user.username)

    @Lazy
    def is_enrolled_for_credit(self):
        record = get_enrollment_in_hierarchy(self.course, self.user)
        return bool(record is not None and record.Scope != ES_PUBLIC)

    def allow_assessment_for_user_in_course(self, asg, *unused_args, **unused_kwargs):
        if self.TEST_OVERRIDE:
            return True
        if not asg.is_non_public:
            return True
        # Note implicit assumption that assignment is in course
        # Warning !!! check if assignment is indeed in the enroll for credit courses
        return self.is_instructor or self.is_enrolled_for_credit
    # BWC
    allow_assignment_for_user_in_course = allow_assessment_for_user_in_course

# BWC
UserEnrolledForCreditInCourseFilter = UserEnrolledForCreditInCourseOrInstructsFilter


@component.adapter(IUser, ICourseInstance)
@interface.implementer(ICourseAssessmentUserFilter)
class AssessmentPolicyExclusionFilter(object):
    """
    If the assignment policies for the course instance exclude the
    filter, we exclude it.

    The policy data is simply the key 'excluded' with a boolean value.
    If there is no policy, this for the assignment, it is allowed.
    """

    def __init__(self, unused_user=None, course=None):
        self.policies = IQAssessmentPolicies(course)

    def allow_assessment_for_user_in_course(self, asg, *unused_args, **unused_kwargs):
        # pylint: disable=too-many-function-args
        return not self.policies.getPolicyForAssessment(asg.ntiid).get('excluded', False)
    allow_assignment_for_user_in_course = allow_assessment_for_user_in_course
AssignmentPolicyExclusionFilter = AssessmentPolicyExclusionFilter


@component.adapter(IUser, ICourseInstance)
@interface.implementer(ICourseAssessmentUserFilter)
class AssessmentPublishExclusionFilter(object):

    def __init__(self, user=None, course=None):
        pass

    def allow_assessment_for_user_in_course(self, asg, *unused_args, **unused_kwargs):
        return asg.is_published()
    # BWC
    allow_assignment_for_user_in_course = allow_assessment_for_user_in_course
