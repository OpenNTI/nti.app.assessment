#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Filters for assignment visibility.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from itertools import chain

from zope import component
from zope import interface

from nti.assessment.interfaces import IQAssessmentPolicies

from nti.common.property import Lazy

from nti.contenttypes.courses.interfaces import ES_PUBLIC

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import is_instructed_by_name
from nti.contenttypes.courses.interfaces import ICourseAssessmentUserFilter

from nti.contenttypes.courses.utils import get_parent_course

from nti.dataserver.interfaces import IUser

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

@interface.implementer(ICourseAssessmentUserFilter)
@component.adapter(IUser, ICourseInstance)
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
		# TODO: Can/should this be role based?
		if is_instructed_by_name(self.course, self.user.username):
			return True

	@Lazy
	def is_enrolled_for_credit(self):
		# CS: check all course sections to see if the user
		# is enroll for credit. This is done b/c when getting the pageinfo
		# there is no guarantee that the Course instance derived from a
		# content unit is the course/section we are enrolled in.
		# this further assume that sections are sharing assigments.
		ref_course = get_parent_course(self.course)
		for course in chain((ref_course,), ref_course.SubInstances.values()):
			record = ICourseEnrollments(course).get_enrollment_for_principal(self.user)
			if record is not None and record.Scope != ES_PUBLIC:
				return True

		# anything except public is for-credit; default to public even if not enrolled
		return False

	def allow_assessment_for_user_in_course(self, asg, user, course):
		if self.TEST_OVERRIDE:
			return True

		# Note implicit assumption that assignment is in course
		if self.is_instructor or self.is_enrolled_for_credit:
			# TODO: check if assignment is indeed in the enroll for credit courses
			return True
		return not asg.is_non_public
	allow_assignment_for_user_in_course = allow_assessment_for_user_in_course  # BWC

UserEnrolledForCreditInCourseFilter = UserEnrolledForCreditInCourseOrInstructsFilter  # BWC

@component.adapter(IUser, ICourseInstance)
@interface.implementer(ICourseAssessmentUserFilter)
class AssessmentPolicyExclusionFilter(object):
	"""
	If the assignment policies for the course instance exclude the
	filter, we exclude it.

	The policy data is simply the key 'excluded' with a boolean value.
	If there is no policy, this for the assignment, it is allowed.
	"""

	def __init__(self, user=None, course=None):
		self.policies = IQAssessmentPolicies(course)

	def allow_assessment_for_user_in_course(self, asg, user=None, course=None):
		excluded = self.policies.getPolicyForAssessment(asg.ntiid).get('excluded', False)
		return not excluded
	allow_assignment_for_user_in_course = allow_assessment_for_user_in_course
AssignmentPolicyExclusionFilter = AssessmentPolicyExclusionFilter
