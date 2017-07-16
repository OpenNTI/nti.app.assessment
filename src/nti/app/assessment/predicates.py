#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component

from zope.security.interfaces import IPrincipal

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalAdministrativeRoleCatalog

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ISystemUserPrincipal

from nti.dataserver.metadata.predicates import BasePrincipalObjects

from nti.dataserver.users.users import User


def get_courses_from_enrollments(user, provided, method):
    for enrollments in component.subscribers((user,), provided):
        for enrollment in getattr(enrollments, method)():
            course = ICourseInstance(enrollment, None)
            if course is not None:
                yield course


@component.adapter(IUser)
class _AssignmentHistoryPrincipalObjects(BasePrincipalObjects):

    def get_enrolled_courses(self, user):
        return get_courses_from_enrollments(user,
                                            IPrincipalEnrollments,
                                            'iter_enrollments')

    def get_instructed_courses(self, user):
        return get_courses_from_enrollments(user,
                                            IPrincipalAdministrativeRoleCatalog,
                                            'iter_administrations')

    def feedback_items(self, feedback, username):
        for x in feedback.Items:
            if self.creator(x) == username:
                yield x

    def metadata_items(self, course, user):
        items = component.queryMultiAdapter((course, user),
                                            IUsersCourseAssignmentMetadata)
        result = []
        if items:
            result.append(items)
            result.extend(items.values())
        return result

    def history_items(self):
        result = []
        for course in self.get_enrolled_courses(self.user):
            items = component.queryMultiAdapter((course, self.user),
                                                IUsersCourseAssignmentHistory)
            if not items:
                continue
            result.append(items)
            for item in items.values():
                result.append(item)
                result.extend(item.sublocations())
                if not item.has_feedback():
                    continue
                result.extend(self.feedback_items(item.Feedback, 
                                                  self.username))
            result.extend(self.metadata_items(course, self.user))
        return result

    def instructor_feedback_items(self):
        result = []
        for course in self.get_instructed_courses(self.user):
            enrollments = ICourseEnrollments(course)
            for record in enrollments.iter_enrollments():
                student = IPrincipal(record, None)
                if student is None:
                    continue
                student = User.get_user(student.id)
                items = component.queryMultiAdapter((course, student),
                                                    IUsersCourseAssignmentHistory)
                if not items:
                    continue
                for item in items:
                    if not item.has_feedback():
                        continue
                    result.extend(self.feedback_items(item.Feedback, 
                                                      self.username))
        return result

    def iter_objects(self):
        result = self.history_items()
        result.extend(self.instructor_feedback_items())
        return result


@component.adapter(IUser)
class _CourseInquiryPrincipalObjects(BasePrincipalObjects):

    def get_enrolled_courses(self, user):
        return get_courses_from_enrollments(user,
                                            IPrincipalEnrollments,
                                            'iter_enrollments')

    def iter_objects(self):
        result = []
        for course in self.get_enrolled_courses(self.user):
            items = component.queryMultiAdapter((course, self.user),
                                                IUsersCourseInquiry)
            if not items:
                continue
            result.append(items)
            for item in items.values():
                result.append(item)
                result.append(item.Submission)
        return result


@component.adapter(ISystemUserPrincipal)
class _SystemEvaluationObjects(BasePrincipalObjects):

    def iter_objects(self):
        for _, item in component.getUtilitiesFor(IQEvaluation):
            if     not IQEditableEvaluation.providedBy(item) \
                or self.is_system_username(self.creator(item)):
                yield item


@component.adapter(IUser)
class _UserEvaluationObjects(BasePrincipalObjects):

    def iter_objects(self):
        for _, item in component.getUtilitiesFor(IQEvaluation):
            if      IQEditableEvaluation.providedBy(item) \
                and self.creator(item) == self.username:
                yield item
