#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import datetime

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from pyramid.threadlocal import get_current_request

from nti.app.assessment.common import get_container_evaluations
from nti.app.assessment.common import is_assignment_non_public_only
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import ALL_ASSIGNMENT_MIME_TYPES

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage

from nti.contentsearch.interfaces import ISearchHitPredicate

from nti.contentsearch.predicates import DefaultSearchHitPredicate

from nti.contenttypes.courses.interfaces import ES_PUBLIC
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_enrolled
from nti.contenttypes.courses.utils import get_enrollment_record
from nti.contenttypes.courses.utils import is_instructed_by_name
from nti.contenttypes.courses.utils import get_courses_for_packages

from nti.dataserver.authorization import ACT_READ

from nti.dataserver.users import User

from nti.traversal.traversal import find_interface


@interface.implementer(ISearchHitPredicate)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _AssignmentFeedbackItemSearchHitPredicate(DefaultSearchHitPredicate):

    __name__ = 'AssignmentFeedback'

    def allow(self, feedback, score, query=None):
        if self.principal is None:
            return True
        else:
            pid = self.principal.id
            user = User.get_user(pid)
            owner = feedback.creator
            course = find_interface(feedback, ICourseInstance, strict=False)
            if      user is not None \
                and (owner == user is not None or is_instructed_by_name(course, pid)):
                return True
        return False


@component.adapter(IQEvaluation)
@interface.implementer(ISearchHitPredicate)
class _EvaluationSearchHitPredicate(DefaultSearchHitPredicate):

    __name__ = 'Evaluation'

    @Lazy
    def request(self):
        return get_current_request()

    def get_courses(self, item):
        course = find_interface(item, ICourseInstance, strict=False)
        if course is not None:
            return (course,)
        else:
            package = find_interface(item, IContentPackage, strict=False)
            if package is not None:
                return get_courses_for_packages(packages=package.ntiid)
        return ()

    def allow(self, item, score, query=None):
        if self.principal is None:
            return True
        else:
            courses = self.get_courses(item)
            if not courses:
                return has_permission(ACT_READ, item, self.request)
            for course in courses or ():
                if     is_instructed_by_name(course, self.principal.id) \
                    or is_enrolled(course, self.principal):
                    return True
        return False


@component.adapter(IQAssignment)
@interface.implementer(ISearchHitPredicate)
class _AssignmentSearchHitPredicate(_EvaluationSearchHitPredicate):

    __name__ = 'Assignment'

    def allow(self, item, score, query=None):
        if self.principal is None:
            return True
        else:
            pid = self.principal.id
            user = User.get_user(pid)
            if user is None:
                return False
            now = datetime.datetime.utcnow()
            courses = self.get_courses(item)
            if not courses:
                return True  # always
            for course in courses or ():
                if is_instructed_by_name(course, self.principal.id):
                    return True
                record = get_enrollment_record(course, user)
                if record is None:
                    continue
                beginning = get_available_for_submission_beginning(item, course)
                if not beginning or now >= beginning:
                    if is_assignment_non_public_only(item, course):
                        if record.Scope != ES_PUBLIC:
                            return True
                    else:
                        return True
        return False


@component.adapter(IContentUnit)
@interface.implementer(ISearchHitPredicate)
class _ContentUnitAssesmentHitPredicate(DefaultSearchHitPredicate):

    __name__ = 'ContentUnitAssesment'

    SEARCH_MTS = ALL_ASSIGNMENT_MIME_TYPES + (SURVEY_MIME_TYPE,)

    def _is_allowed(self, ntiid, query=None):
        evaluations = get_container_evaluations((ntiid,),
                                                mimetypes=self.SEARCH_MTS)
        return not bool(evaluations)

    def allow(self, item, score, query=None):
        if self.principal is None:
            return True
        return self._is_allowed(item.ntiid, query)
