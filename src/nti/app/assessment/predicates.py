#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
 
from ZODB.POSException import POSError
 
from nti.dataserver.interfaces import IUser
 
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments

from nti.metadata.predicates import BasePrincipalObjects
 
from nti.site.hostpolicy import run_job_in_all_host_sites

from .interfaces import IUsersCourseAssignmentHistory

@component.adapter(IUser)
class _AssignmentHistoryPrincipalObjects(BasePrincipalObjects):
 
    def iter_objects(self):
        result = []
        user = self.user
        def _collector():
            for enrollments in component.subscribers( (user,), IPrincipalEnrollments):
                for enrollment in enrollments.iter_enrollments():
                    try:
                        course = ICourseInstance(enrollment, None)
                        items = component.queryMultiAdapter( (course, user),
                                                              IUsersCourseAssignmentHistory )
                        if not items:
                            continue
                        result.append(items)
                        for item in items:
                            result.append(item)
                            submission = item.Submission
                            result.append(submission)
                    except (TypeError, POSError):
                        continue
        run_job_in_all_host_sites(_collector)
        return result
