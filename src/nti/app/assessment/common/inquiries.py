#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import itertools

from datetime import datetime

from zope import component

from zope.intid.interfaces import IIntIds

from zope.schema.interfaces import RequiredMissing

from nti.app.assessment.assignment_filters import AssessmentPolicyExclusionFilter

from nti.app.assessment.common.evaluations import proxy
from nti.app.assessment.common.evaluations import get_course_evaluations
from nti.app.assessment.common.evaluations import get_evaluation_courses

from nti.app.assessment.common.policy import get_policy_for_assessment

from nti.app.assessment.common.submissions import inquiry_submissions

from nti.app.assessment.common.utils import get_evaluation_catalog_entry
from nti.app.assessment.common.utils import get_available_for_submission_ending

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseInquiry

from nti.assessment.interfaces import DISCLOSURE_NEVER
from nti.assessment.interfaces import DISCLOSURE_ALWAYS
from nti.assessment.interfaces import DISCLOSURE_SUBMISSION
from nti.assessment.interfaces import INQUIRY_MIME_TYPES

from nti.assessment.interfaces import IQAggregatedInquiry
from nti.assessment.interfaces import IQInquirySubmission

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver.metadata.index import IX_MIMETYPE
from nti.dataserver.metadata.index import IX_CONTAINERID

from nti.dataserver.metadata.index import get_metadata_catalog

from nti.zope_catalog.catalog import ResultSet

logger = __import__('logging').getLogger(__name__)


def find_course_for_inquiry(inquiry, user, exc=True):
    # Check that they're enrolled in the course that has the inquiry
    course = component.queryMultiAdapter((inquiry, user), ICourseInstance)
    if course is None and exc:
        raise RequiredMissing("Course cannot be found")
    return course


def get_course_from_inquiry(inquiry, user=None, exc=False):
    result = get_evaluation_catalog_entry(inquiry)
    result = ICourseInstance(result, None)

    if result is None:
        courses = get_evaluation_courses(inquiry)
        result = courses[0] if len(courses) == 1 else None

    # could not find a course .. try adapter
    if result is None and user is not None:
        result = find_course_for_inquiry(inquiry, user, exc=exc)
    return result


def get_course_inquiries(context, mimetypes=None, do_filtering=True):
    items = get_course_evaluations(context, mimetypes=mimetypes or INQUIRY_MIME_TYPES)
    ntiid = ICourseCatalogEntry(context).ntiid
    if do_filtering:
        # Filter out excluded assignments so they don't show in the gradebook
        # either
        course = ICourseInstance(context)
        _filter = AssessmentPolicyExclusionFilter(course=course)
        surveys = [proxy(x, catalog_entry=ntiid) for x in items
                   if _filter.allow_assessment_for_user_in_course(x, course=course)]
    else:
        surveys = [proxy(x, catalog_entry=ntiid) for x in items]
    return surveys


def can_disclose_inquiry(inquiry, user, context=None):
    course = ICourseInstance(context, None)
    if course is not None:
        policy = get_policy_for_assessment(inquiry.ntiid, course)
    else:
        policy = None
    not_after = get_available_for_submission_ending(inquiry, course)

    # get disclosure policy
    if policy and 'disclosure' in policy:
        disclosure = policy['disclosure'] or inquiry.disclosure
    else:
        disclosure = inquiry.disclosure

    # eval
    result = disclosure == DISCLOSURE_ALWAYS
    if not result and disclosure != DISCLOSURE_NEVER:
        if disclosure == DISCLOSURE_SUBMISSION:
            result = _has_inquiry_submission(course, user, inquiry)
        else:
            result = not_after and datetime.utcnow() >= not_after
    return result


def _has_inquiry_submission(course, user, inquiry):
    course_inquiry = component.getMultiAdapter((course, user),
                                               IUsersCourseInquiry)
    return inquiry.ntiid in course_inquiry


def aggregate_course_inquiry(inquiry, course, *items):
    result = None
    submissions = inquiry_submissions(inquiry, course)
    items = itertools.chain(submissions, items)
    for item in items:
        if not IUsersCourseInquiryItem.providedBy(item):  # always check
            continue
        submission = item.Submission
        aggregated = IQAggregatedInquiry(submission)
        if result is None:
            result = aggregated
        else:
            result += aggregated
    return result


def aggregate_page_inquiry(containerId, mimeType, *items):
    catalog = get_metadata_catalog()
    intids = component.getUtility(IIntIds)
    query = {
        IX_MIMETYPE: {'any_of': (mimeType,)},
        IX_CONTAINERID: {'any_of': (containerId,)}
    }
    result = None
    uids = catalog.apply(query) or ()
    items = itertools.chain(ResultSet(uids, intids, True), items)
    for item in items:
        if not IQInquirySubmission.providedBy(item):  # always check
            continue
        aggregated = IQAggregatedInquiry(item)
        if result is None:
            result = aggregated
        else:
            result += aggregated
    return result
