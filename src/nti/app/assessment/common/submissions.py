#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

import six

from zope import component

from zope.intid.interfaces import IIntIds

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.common.hostpolicy import get_resource_site_name

from nti.app.assessment.common.policy import get_policy_full_submission

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

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


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


def get_all_submissions_courses(context, sites=(), index_name=IX_ASSESSMENT_ID):
    result = set()
    for sub in get_all_submissions(context, sites, index_name):
        course = find_interface(sub, ICourseInstance, strict=False)
        result.add(course)
    result.discard(None)
    return tuple(result)


def get_submission_intids_for_courses(context, courses=(), index_name=IX_ASSESSMENT_ID):
    """
    Return all submissions intids for the given evaluation object and courses
    """
    courses = to_course_list(courses)
    if not courses:
        return
    else:
        # We only index by assignment, so fetch all assignments/surveys for
        # our context; plus by our context ntiid.
        assignments = get_containers_for_evaluation_object(context)
        context_ntiids = [x.ntiid for x in assignments] if assignments else []
        context_ntiid = getattr(context, 'ntiid', context)
        context_ntiids.append(context_ntiid)
        catalog = get_submission_catalog()
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
        return catalog.apply(query)


def get_submissions(*args, **kwargs):
    """
    Return all submissions for the given evaluation object.
    """
    result = get_submission_intids_for_courses(*args, **kwargs)
    if result is not None:
        intids = component.getUtility(IIntIds)
        result = (intids.queryObject(x) for x in result)
        result = [x for x in result if IUsersCourseSubmissionItem.providedBy(x)]
    return result


def has_submissions(*args, **kwargs):
    """
    Returns whether the given evaluation has any submissions in the given
    `courses` sequence.
    """
    # Querying from submission catalog may result in stale results.
    # Instead of reifying, we check against the intids.
    result = get_submission_intids_for_courses(*args, **kwargs)
    if result is not None:
        intids = component.getUtility(IIntIds)
        for submission_intid in result:
            if submission_intid in intids.refs:
                return True
    return False


def has_inquiry_submissions(context, course, subinstances=True):
    """
    Returns whether the given evaluation has any submissions in the given
    `courses` sequence.
    """
    course = ICourseInstance(course, None)
    courses = get_courses(course, subinstances=subinstances)
    return has_submissions(context, courses=courses)


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

def check_full_submission(submission, evaluation, course):
    """
    For the given submission, validate if the user has responses for all
    questions/parts in the evaluation, if required. We raise a 422 if not.
    
    We handle both assignment and survey submissions here.
    """
    if get_policy_full_submission(evaluation, course):
        for submission_part in submission.parts:
            try:
                # Assignment
                submitted_questions = submission_part.questions
            except AttributeError:
                # Inquiry
                submitted_questions = (submission_part,)
            for question in submitted_questions:
                if not question.parts or None in question.parts:
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': _(u'Must answer all questions.'),
                                     },
                                     None)