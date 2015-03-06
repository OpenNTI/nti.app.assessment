#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from functools import partial

from zope import component
 
from ZODB.POSException import POSError
 
from nti.dataserver.interfaces import IUser
 
from nti.app.products.courseware.interfaces import IPrincipalAdministrativeRoleCatalog

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments

from nti.metadata.predicates import BasePrincipalObjects
 
from nti.site.hostpolicy import run_job_in_all_host_sites

from .interfaces import IUsersCourseAssignmentHistory

@component.adapter(IUser)
class _AssignmentHistoryPrincipalObjects(BasePrincipalObjects):
 
    def _feedbackitem_collector(self, feedback, creator):
        for x in feedback.Items:
            if x.creator == creator:
                yield x

    def _enrollment_collector(self, result):
        user = self.user
        for enrollments in component.subscribers( (user,), IPrincipalEnrollments):
            for enrollment in enrollments.iter_enrollments():
                try:
                    course = ICourseInstance(enrollment, None)
                    items = component.queryMultiAdapter( (course, user),
                                                          IUsersCourseAssignmentHistory )
                    if not items:
                        continue
                    result.append(items)
                    for item in items.values():
                        result.append(item)
                        result.append(item.Submission)
                        result.append(item.pendingAssessment)
                        # check feedback
                        feedback = item.Feedback
                        if feedback is not None:
                            result.append(feedback)
                            result.extend(self._feedbackitem_collector(feedback, user))
                except (TypeError, POSError):
                    continue
        return result
    
    def _feedback_collector(self, result):
        user = self.user
        for roles in component.subscribers( (user,), IPrincipalAdministrativeRoleCatalog):
            for role in roles.iter_administrations():
                try:
                    course = ICourseInstance(role, None)
                    if course is None:
                        continue
                    enrollments  = ICourseEnrollments(course)
                    for record in enrollments.iter_enrollments():
                        student = IUser(record.principal, None)
                        if student is None:
                            continue
                        items = component.queryMultiAdapter( (course, student),
                                                             IUsersCourseAssignmentHistory )
                        if not items:
                            continue
                        for item in items:
                            feedback = item.Feedback
                            if feedback is not None:
                                result.extend(self._feedbackitem_collector(feedback, user))
                except (TypeError, POSError):
                    continue
        return result
    
    def _collector(self, result):
        self._feedback_collector(result)
        self._enrollment_collector(result)
        
    def iter_objects(self):
        result = []
        run_job_in_all_host_sites(partial(self._collector, result))
        return result
