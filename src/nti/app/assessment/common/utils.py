#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope.security.interfaces import IPrincipal

from nti.app.authentication import get_remote_user

from nti.assessment.interfaces import NTIID_TYPE

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.coremetadata.interfaces import SYSTEM_USER_NAME

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import get_provider
from nti.ntiids.ntiids import get_specific
from nti.ntiids.ntiids import make_specific_safe

from nti.publishing.interfaces import IPublishable

from nti.zodb.containers import time_to_64bit_int

NTI = u'NTI'
NAQ = NTIID_TYPE


def get_user(user=None, remote=False, request=None):
    if user is None and remote:
        user = get_remote_user(request)
    elif IPrincipal.providedBy(user):
        user = user.id
    if user is not None and not IUser.providedBy(user):
        user = User.get_user(str(user))
    return user


def get_courses(context, subinstances=True):
    course = ICourseInstance(context, None)
    if subinstances:
        courses = get_course_hierarchy(course) if course is not None else ()
    else:
        courses = (course,) if course is not None else ()
    return courses


def to_course_list(courses=()):
    if ICourseCatalogEntry.providedBy(courses):
        courses = ICourseInstance(courses)
    if ICourseInstance.providedBy(courses):
        courses = (courses,)
    elif isinstance(courses, (list, tuple, set)):
        courses = tuple(courses)
    return courses or ()


def get_entry_ntiids(courses=()):
    courses = to_course_list(courses) or ()
    entries = (ICourseCatalogEntry(x, None) for x in courses)
    return {x.ntiid for x in entries if x is not None}


def make_evaluation_ntiid(kind, base=None, extra=None):
    # get kind
    if IQAssignment.isOrExtends(kind):
        kind = u'assignment'
    elif IQuestionSet.isOrExtends(kind):
        kind = u'questionset'
    elif IQuestion.isOrExtends(kind):
        kind = u'question'
    elif IQPoll.isOrExtends(kind):
        kind = u'poll'
    elif IQSurvey.isOrExtends(kind):
        kind = u'survey'
    else:
        kind = str(kind)

    creator = SYSTEM_USER_NAME
    current_time = time_to_64bit_int(time.time())
    provider = get_provider(base) or NTI if base else NTI

    specific_base = get_specific(base) if base else None
    if specific_base:
        specific_base += u'.%s.%s.%s' % (kind, creator, current_time)
    else:
        specific_base = u'%s.%s.%s' % (kind, creator, current_time)

    if extra:
        specific_base = specific_base + u".%s" % extra
    specific = make_specific_safe(specific_base)

    ntiid = make_ntiid(nttype=NAQ,
                       base=base,
                       provider=provider,
                       specific=specific)
    return ntiid


def get_policy_field(assignment, course, field):
    policy = IQAssessmentPolicies(course, None)
    assignment_ntiid = getattr(assignment, 'ntiid', assignment)
    result = policy.get(assignment_ntiid, field, False)
    return result


def is_published(context):
    return not IPublishable.providedBy(context) or context.is_published()


def get_available_for_submission_beginning(assesment, context=None):
    course = ICourseInstance(context, None)
    dates = IQAssessmentDateContext(course, None)
    if dates is not None:
        result = dates.of(assesment).available_for_submission_beginning
    else:
        result = assesment.available_for_submission_beginning
    return result


def get_available_for_submission_ending(assesment, context=None):
    course = ICourseInstance(context, None)
    dates = IQAssessmentDateContext(course, None)
    if dates is not None:
        result = dates.of(assesment).available_for_submission_ending
    else:
        result = assesment.available_for_submission_ending
    return result
