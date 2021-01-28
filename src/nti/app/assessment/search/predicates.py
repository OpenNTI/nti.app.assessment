#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import datetime

from pyramid.threadlocal import get_current_request

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from nti.app.assessment.common.evaluations import is_assignment_available
from nti.app.assessment.common.evaluations import get_container_evaluations
from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.common.submissions import has_submitted_assigment

from nti.app.assessment.common.utils import get_available_for_submission_beginning

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import ALL_ASSIGNMENT_MIME_TYPES

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQTimedAssignment

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

from nti.dataserver.interfaces import IUser

from nti.dataserver.users.users import User

from nti.publishing.interfaces import IPublishable

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


@interface.implementer(ISearchHitPredicate)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _AssignmentFeedbackItemSearchHitPredicate(DefaultSearchHitPredicate):

    __name__ = u'AssignmentFeedback'

    def allow(self, feedback, unused_score, unused_query=None):  # pylint: disable=arguments-differ
        if self.principal is None:
            return True
        else:
            pid = self.principal.id
            user = User.get_user(pid)
            owner = feedback.creator
            course = find_interface(feedback, ICourseInstance, strict=False)
            if      IUser.providedBy(user) \
                and (owner == user is not None or is_instructed_by_name(course, pid)):
                return True
        return False


@component.adapter(IQEvaluation)
@interface.implementer(ISearchHitPredicate)
class _EvaluationSearchHitPredicate(DefaultSearchHitPredicate):

    __name__ = u'Evaluation'

    @Lazy
    def request(self):
        return get_current_request()

    def is_published(self, item):
        return not IPublishable.providedBy(item) or item.is_published()

    def get_courses(self, item):
        course = find_interface(item, ICourseInstance, strict=False)
        if course is not None:
            return (course,)
        else:
            package = find_interface(item, IContentPackage, strict=False)
            if package is not None:
                return get_courses_for_packages(packages=package.ntiid)
        return ()

    def check_visible(self, user, course, item):
        # Get containing assignments/surveys
        for container in get_containers_for_evaluation_object(item):
            if IQTimedAssignment.providedBy(container):
                if has_submitted_assigment(course, user, container):
                    return True
            elif IQAssignment.providedBy(container):
                # XXX: Use this in assingment predicate below?
                if is_assignment_available(container, course, user):
                    return True
            elif IQSurvey.providedBy(container):
                # TODO: Improve this branch
                return True

    def allow(self, item, unused_score, unused_query=None):  # pylint: disable=arguments-differ
        if self.principal is None:
            return True
        else:
            if not self.is_published(item):
                # XXX: Just creator acl?
                return has_permission(ACT_READ, item, self.request)
            courses = self.get_courses(item)
            if not courses:
                return has_permission(ACT_READ, item, self.request)
            pid = self.principal.id
            user = User.get_user(pid)
            for course in courses:
                if     (   is_instructed_by_name(course, self.principal.id) \
                        or is_enrolled(course, self.principal)) \
                    and self.check_visible(user, course, item):
                    return True
        return False


@component.adapter(IQAssignment)
@interface.implementer(ISearchHitPredicate)
class _AssignmentSearchHitPredicate(_EvaluationSearchHitPredicate):

    __name__ = u'Assignment'

    def allow(self, item, unused_score, unused_query=None):
        if self.principal is None:
            return True
        else:
            pid = self.principal.id
            user = User.get_user(pid)
            if not IUser.providedBy(user):
                return False
            if not self.is_published(item):
                return has_permission(ACT_READ, item, self.request)
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
                # Enrollment
                if IQTimedAssignment.providedBy(item):
                    if has_submitted_assigment(course, user, item):
                        return True
                else:
                    beginning = get_available_for_submission_beginning(item, course)
                    if not beginning or now >= beginning:
                        if item.is_non_public:
                            if record.Scope != ES_PUBLIC:
                                return True
                        else:
                            return True
        return False


@component.adapter(IContentUnit)
@interface.implementer(ISearchHitPredicate)
class _ContentUnitAssesmentHitPredicate(DefaultSearchHitPredicate):

    __name__ = u'ContentUnitAssesment'

    SEARCH_MTS = ALL_ASSIGNMENT_MIME_TYPES + (SURVEY_MIME_TYPE,)

    def _is_allowed(self, ntiid, unused_query=None):
        evaluations = get_container_evaluations((ntiid,),
                                                mimetypes=self.SEARCH_MTS)
        return not bool(evaluations)

    def allow(self, item, unused_score, query=None):  # pylint: disable=arguments-differ
        if self.principal is None:
            return True
        return self._is_allowed(item.ntiid, query)
