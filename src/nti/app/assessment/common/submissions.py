#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from zope import component

from zope.intid.interfaces import IIntIds

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.common.hostpolicy import get_resource_site_name

from nti.app.assessment.common.utils import get_user
from nti.app.assessment.common.utils import get_courses
from nti.app.assessment.common.utils import to_course_list
from nti.app.assessment.common.utils import get_entry_ntiids

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import IX_SUBMITTED
from nti.app.assessment.index import IX_ASSESSMENT_ID

from nti.app.assessment.index import get_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseSubmissionItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.app.externalization.error import raise_json_error

from nti.assessment.interfaces import IQEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance


def has_assigments_submitted(context, user):
    user = get_user(user)
    course = ICourseInstance(context, None)
    histories = component.queryMultiAdapter((course, user),
                                            IUsersCourseAssignmentHistory)
    return bool(histories is not None and len(histories) > 0)


def has_submitted_assigment(context, user, assigment):
    user = get_user(user)
    course = ICourseInstance(context, None)
    histories = component.queryMultiAdapter((course, user),
                                            IUsersCourseAssignmentHistory)
    ntiid = getattr(assigment, 'ntiid', assigment)
    return bool(histories and ntiid in histories)


def get_all_submissions(context, sites=(), index_name=IX_ASSESSMENT_ID):
    if IQEvaluation.providedBy(context):
        ntiid = context.ntiid
        if not sites:
            name = get_resource_site_name(context)
            sites = (name,) if name else ()
    else:
        ntiid = context
    query = {
        index_name: {'any_of': (ntiid,)}
    }
    if isinstance(sites, six.string_types):
        sites = sites.split()
    if sites:
        query[IX_SITE] = {'any_of': sites}
    # execute query
    catalog = get_submission_catalog()
    intids = component.getUtility(IIntIds)
    for doc_id in catalog.apply(query) or ():
        obj = intids.queryObject(doc_id)
        if IUsersCourseSubmissionItem.providedBy(obj):
            yield obj


def get_submissions(context, courses=(), index_name=IX_ASSESSMENT_ID):
    """
    Return all submissions for the given evaluation object.
    """
    courses = to_course_list(courses)
    if not courses:
        return ()
    else:
        # We only index by assignment, so fetch all assignments/surveys for
        # our context; plus by our context ntiid.
        assignments = get_containers_for_evaluation_object(context)
        context_ntiids = [x.ntiid for x in assignments] if assignments else []
        context_ntiid = getattr(context, 'ntiid', context)
        context_ntiids.append(context_ntiid)

        catalog = get_submission_catalog()
        intids = component.getUtility(IIntIds)
        entry_ntiids = get_entry_ntiids(courses)

        query = {
            IX_COURSE: {'any_of': entry_ntiids},
            index_name: {'any_of': context_ntiids}
        }

        # May not have sites for community based courses (tests?).
        sites = {get_resource_site_name(x) for x in courses}
        sites.discard(None)  # tests
        if sites:
            query[IX_SITE] = {'any_of': sites}

        result = []
        for doc_id in catalog.apply(query) or ():
            obj = intids.queryObject(doc_id)
            if IUsersCourseSubmissionItem.providedBy(obj):
                result.append(obj)
        return result


def has_submissions(context, courses=()):
    for _ in get_submissions(context, courses):
        return True
    return False


def evaluation_submissions(context, course, subinstances=True):
    course = ICourseInstance(course, None)
    result = get_submissions(context,
                             index_name=IX_SUBMITTED,
                             courses=get_courses(course, subinstances=subinstances))
    return result


def inquiry_submissions(context, course, subinstances=True):
    course = ICourseInstance(course, None)
    result = get_submissions(context,
                             index_name=IX_ASSESSMENT_ID,
                             courses=get_courses(course, subinstances=subinstances))
    return result


def has_inquiry_submissions(context, course, subinstances=True):
    for _ in inquiry_submissions(context, course, subinstances):
        return True
    return False


def has_submitted_inquiry(context, user, assigment):
    user = get_user(user)
    course = ICourseInstance(context, None)
    histories = component.queryMultiAdapter((course, user),
                                            IUsersCourseInquiry)
    ntiid = getattr(assigment, 'ntiid', assigment)
    return bool(histories and ntiid in histories)


def check_submission_version(submission, evaluation):
    """
    Make sure the submitted version matches our assignment version.
    If not, the client needs to refresh and re-submit to avoid
    submitting stale, incorrect data for this assignment.
    """
    evaluation_version = evaluation.version
    if      evaluation_version \
        and evaluation_version != getattr(submission, 'version', ''):
        raise_json_error(get_current_request(),
                         hexc.HTTPConflict,
                         {
                             'message': _(u'Evaluation version has changed.'),
                         },
                         None)
