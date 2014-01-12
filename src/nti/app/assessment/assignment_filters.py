#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Filters for assignment visibility.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import component

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import is_instructed_by_name
from nti.dataserver.interfaces import IUser
from .interfaces import ICourseAssignmentUserFilter
from nti.app.products.courseware.interfaces import ILegacyCourseInstanceEnrollment

from nti.utils.property import Lazy

###
## ACLs
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
##


@interface.implementer(ICourseAssignmentUserFilter)
@component.adapter(IUser, ICourseInstance)
class UserEnrolledForCreditInCourseOrInstructsFilter(object):
	"""
	Allows access to the assignment if the user is enrolled
	for credit, or if the assignment designates that it is available
	to everyone.
	"""


	def __init__(self, user, course):
		self.user = user
		self.course = course

	@Lazy
	def is_instructor(self):
		if is_instructed_by_name(self.course, self.user.username):
			return True

	@Lazy
	def is_enrolled_for_credit(self):
		enrollment = component.queryMultiAdapter( (self.course, self.user),
												  ILegacyCourseInstanceEnrollment)
		return getattr(enrollment, 'LegacyEnrollmentStatus', 'Open') == 'ForCredit'

	def allow_assignment_for_user_in_course(self, asg, user, course):
		# Note implicit assumption that assignment is in course
		if self.is_instructor or self.is_enrolled_for_credit:
			return True

		return not asg.is_non_public

UserEnrolledForCreditInCourseFilter = UserEnrolledForCreditInCourseOrInstructsFilter # BWC
