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
from datetime import timedelta

import six

from ZODB import loglevels

from zope import component

from zope.intid.interfaces import IIntIds

from zope.proxy import isProxy
from zope.proxy import ProxyBase

from zope.schema.interfaces import RequiredMissing

from nti.app.assessment.assignment_filters import AssessmentPolicyExclusionFilter

from nti.app.assessment.common.utils import is_published
from nti.app.assessment.common.utils import get_policy_field
from nti.app.assessment.common.utils import get_evaluation_catalog_entry
from nti.app.assessment.common.utils import get_available_for_submission_ending
from nti.app.assessment.common.utils import get_available_for_submission_beginning

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_CONTAINERS
from nti.app.assessment.index import IX_CONTAINMENT
from nti.app.assessment.index import IX_MIMETYPE as IX_ASSESS_MIMETYPE

from nti.app.assessment.index import get_evaluation_catalog

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.app.authentication import get_remote_user

from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE
from nti.assessment.interfaces import QUESTION_BANK_MIME_TYPE
from nti.assessment.interfaces import ALL_ASSIGNMENT_MIME_TYPES

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQDiscussionAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.assessment.interfaces import IPlaceholderAssignmentSubmission

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IGlobalContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IGlobalContentPackageLibrary

from nti.contenttypes.completion.utils import get_completed_item

from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussion

from nti.contenttypes.courses.discussions.utils import get_implied_by_scopes

from nti.contenttypes.courses.interfaces import ES_ALL
from nti.contenttypes.courses.interfaces import ES_PUBLIC

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSubInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.legacy_catalog import ILegacyCourseInstance

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.utils import get_parent_course

from nti.dataserver.contenttypes.forums.interfaces import ITopic

from nti.dataserver.users.users import User

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.site import get_component_hierarchy_names

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


def get_evaluation_containment(ntiid, sites=None, intids=None):
    result = []
    sites = get_component_hierarchy_names() if not sites else sites
    sites = sites.split() if isinstance(sites, six.string_types) else sites
    query = {
        IX_SITE: {'any_of': sites},
        IX_CONTAINMENT: {'any_of': (ntiid,)}
    }
    catalog = get_evaluation_catalog()
    intids = component.getUtility(IIntIds) if intids is None else intids
    for uid in catalog.apply(query) or ():
        container = intids.queryObject(uid)
        if container is not None and container.ntiid != ntiid:
            result.append(container)
    return result


def get_evaluation_containers(evaluation):
    result = []
    catalog = get_evaluation_catalog()
    for ntiid in catalog.get_containers(evaluation):
        container = find_object_with_ntiid(ntiid) if ntiid else None
        if container is not None:
            result.append(container)
    return result


def get_container_evaluations(context, sites=None, intids=None, mimetypes=None):
    if isinstance(context, six.string_types):
        containers = context.split()
    elif IContentUnit.providedBy(context):
        containers = (context.ntiid,)
    else:
        containers = context

    sites = get_component_hierarchy_names() if not sites else sites
    sites = sites.split() if isinstance(sites, six.string_types) else sites
    query = {
        IX_SITE: {'any_of': sites},
        IX_CONTAINERS: {'any_of': containers},
    }
    if isinstance(mimetypes, six.string_types):
        mimetypes = mimetypes.split()
    if mimetypes:
        query[IX_ASSESS_MIMETYPE] = {'any_of': mimetypes}

    result = []
    catalog = get_evaluation_catalog()
    intids = component.getUtility(IIntIds) if intids is None else intids
    for uid in catalog.apply(query) or ():
        evaluation = intids.queryObject(uid)
        if IQEvaluation.providedBy(evaluation):  # extra check
            result.append(evaluation)
    return result


def get_course_evaluations(context, sites=None, intids=None, mimetypes=None,
                           parent_course=False):
    if isinstance(context, six.string_types):
        ntiid = context
        containers = (ntiid,)
    else:
        course = ICourseInstance(context)
        entry = ICourseCatalogEntry(course)
        if ILegacyCourseInstance.providedBy(course):
            # Global courses cannot use index.
            return get_course_assessment_items(course)
        # We index assessment items before our courses; so
        # make sure we also check for course packages.
        ntiid = entry.ntiid
        containers = [ntiid]
        if ICourseSubInstance.providedBy(course) and parent_course:
            # Make sure we pull for both subinstance and parent if asked for.
            parent_course = get_parent_course(course)
            parent_entry = ICourseCatalogEntry(parent_course)
            if parent_entry:
                containers.append(parent_entry.ntiid)
        packages = get_course_packages(course)
        containers.extend((x.ntiid for x in packages))

    return get_container_evaluations(containers, sites, intids, mimetypes)


class AssessmentItemProxy(ProxyBase):

    # pylint: disable=property-on-old-class

    ContentUnitNTIID = property(
        lambda s: s.__dict__.get('_v_content_unit'),
        lambda s, v: s.__dict__.__setitem__('_v_content_unit', v))

    CatalogEntryNTIID = property(
        lambda s: s.__dict__.get('_v_catalog_entry'),
        lambda s, v: s.__dict__.__setitem__('_v_catalog_entry', v))

    def __new__(cls, base, *unused_args, **unused_kwargs):
        return ProxyBase.__new__(cls, base)

    def __init__(self, base, content_unit=None, catalog_entry=None):
        # pylint: disable=non-parent-init-called
        ProxyBase.__init__(self, base)
        self.ContentUnitNTIID = content_unit
        self.CatalogEntryNTIID = catalog_entry


def proxy(item, content_unit=None, catalog_entry=None):
    if not isProxy(item, AssessmentItemProxy):
        item = AssessmentItemProxy(item)
    item.ContentUnitNTIID = content_unit or item.ContentUnitNTIID
    item.CatalogEntryNTIID = catalog_entry or item.CatalogEntryNTIID
    return item


def same_content_unit_file(unit1, unit2):
    try:
        return unit1.filename.split('#', 1)[0] == unit2.filename.split('#', 1)[0]
    except (AttributeError, IndexError):
        return False


def get_unit_assessments(unit):
    result = []
    try:
        container = IQAssessmentItemContainer(unit)
        # pylint: disable=too-many-function-args
        result.extend(container.assessments())
    except TypeError:
        pass
    return result or ()


def get_assessment_items_from_unit(contentUnit):

    def recur(unit, accum):
        if same_content_unit_file(unit, contentUnit):
            qs = get_unit_assessments(unit)
            accum.update({q.ntiid: q for q in qs or ()})
            for child in unit.children or ():
                recur(child, accum)

    result = dict()
    recur(contentUnit, result)
    return result


def get_content_packages_assessment_items(package):
    result = []
    def _recur(unit):
        items = get_unit_assessments(unit)
        for item in items:
            item = proxy(item, content_unit=unit.ntiid)
            result.append(item)
        for child in unit.children or ():
            _recur(child)
    _recur(package)
    return result


def get_course_assessment_items(context):
    """
    Retrieve all assessment items from our course's content packages.
    """
    packages = get_course_packages(context)
    assessments = None if len(packages) <= 1 else list()
    for package in packages:
        # Assesments should be proxied
        iterable = get_content_packages_assessment_items(package)
        if assessments is None:
            assessments = iterable
        else:
            assessments.extend(iterable)
    return assessments or ()


def find_course_for_evaluation(evaluation, user, exc=True):
    # Check that they're enrolled in the course that has the assignment
    course = component.queryMultiAdapter((evaluation, user), ICourseInstance)
    if course is None:
        # For BWC, we also check to see if we can just get
        # one based on the content package of the assignment, not
        # checking enrollment.
        # 1) Drop this
        package = find_interface(evaluation, IContentPackage, strict=False)
        course = ICourseInstance(package, None)
        if course is not None:
            logger.log(loglevels.TRACE,
                       "No enrollment found, assuming generic course. Tests only?")

    # If one does not exist, we cannot grade because we have nowhere
    # to dispatch to.
    if course is None and exc:
        raise RequiredMissing("Course cannot be found")
    return course
find_course_for_assignment = find_course_for_evaluation  # BWC


def get_evaluation_courses(evaluation):
    result = []
    for container in get_evaluation_containers(evaluation):
        if     ICourseInstance.providedBy(container) \
            or ICourseCatalogEntry.providedBy(container):
            result.append(ICourseInstance(container))
    return result


def get_course_from_evaluation(evaluation, user=None, catalog=None, exc=False):
    entry = get_evaluation_catalog_entry(evaluation, catalog)
    result = ICourseInstance(entry, None)

    # Try catalog first for speed; only return if single course found.
    catalog_courses = None
    if result is None:
        catalog_courses = get_evaluation_courses(evaluation)
        result = catalog_courses[0] if len(catalog_courses) == 1 else None

    # could not find a course .. try adapter; this validates enrollment...
    if result is None and user is not None:
        result = find_course_for_evaluation(evaluation, user, exc=exc)

    # If nothing, fall back to whatever randomly comes up in catalog first.
    # Needed when determining if user is instructor of evaluation course.
    if result is None:
        result = catalog_courses[0] if catalog_courses else None
    return result
get_course_from_assignment = get_course_from_evaluation  # BWC


def assignment_comparator(a, b):
    a_end = a.available_for_submission_ending
    b_end = b.available_for_submission_ending
    if a_end and b_end:
        return -1 if a_end < b_end else 1

    a_begin = a.available_for_submission_beginning
    b_begin = b.available_for_submission_beginning
    if a_begin and b_begin:
        return -1 if a_begin < b_begin else 1
    return 0


def get_all_course_assignments(context):
    """
    Get all un-proxied, non-filtered course assignments for the given context.
    This is a relatively expensive call, because we fetch assignments in
    content packages (necessary for new content backed assignments) and then
    look for all API-created assignments to merge with.
    """
    seen = set()
    results = []
    package_items = get_course_assessment_items(context)
    # For API created assignments, get from parent if we're a subinstance.
    course_items = get_course_assignments(context, sort=False,
                                          do_filtering=False,
                                          parent_course=True)
    for item in itertools.chain(package_items, course_items):
        if not IQAssignment.providedBy(item) or item.ntiid in seen:
            continue
        seen.add(item.ntiid)
        results.append(item)
    return results


def get_course_assignments(context, sort=True, reverse=False, do_filtering=True,
                           parent_course=False):
    items = get_course_evaluations(context,
                                   mimetypes=ALL_ASSIGNMENT_MIME_TYPES,
                                   parent_course=parent_course)
    ntiid = getattr(ICourseCatalogEntry(context, None), 'ntiid', None)
    if do_filtering:
        # Filter out excluded assignments so they don't show in the gradebook
        # either
        course = ICourseInstance(context)
        _filter = AssessmentPolicyExclusionFilter(course=course)
        assignments = [proxy(x, catalog_entry=ntiid) for x in items
                       if IQAssignment.providedBy(x)
                       and _filter.allow_assessment_for_user_in_course(x, course=course)]
    else:
        assignments = [
            proxy(x, catalog_entry=ntiid) for x in items if IQAssignment.providedBy(x)
        ]
    if sort:
        assignments = sorted(assignments,
                             cmp=assignment_comparator,
                             reverse=reverse)
    return assignments


def get_course_self_assessments(context, exclude_editable=True):
    """
    Given an :class:`.ICourseInstance`, return a list of all
    the \"self assessments\" in the course. Self-assessments are
    defined as top-level question sets that are not used within an assignment
    in the course.

    :param exclude_editable Exclude editable evaluations. Currently editable
        question sets are only creatable/editable underneath API created
        assignments.
    """
    result = list()
    qsids_to_strip = set()
    query_types = [QUESTION_SET_MIME_TYPE, QUESTION_BANK_MIME_TYPE]
    query_types.extend(ALL_ASSIGNMENT_MIME_TYPES)
    items = get_course_evaluations(context, mimetypes=query_types)

    for item in items:
        if IQAssignment.providedBy(item):
            qsids_to_strip.add(item.ntiid)
            for assignment_part in item.parts:
                question_set = assignment_part.question_set
                qsids_to_strip.add(question_set.ntiid)
                for question in question_set.questions:
                    qsids_to_strip.add(question.ntiid)
        elif not IQuestionSet.providedBy(item):
            qsids_to_strip.add(item.ntiid)
        elif exclude_editable and IQEditableEvaluation.providedBy(item):
            # Seems like eventually we'll want to return these.
            # We probably eventually want to mark question-sets that
            # are self-assessments.
            qsids_to_strip.add(item.ntiid)
        else:
            result.append(item)

    # Now remove the forbidden
    result = [x for x in result if x.ntiid not in qsids_to_strip]
    return result


def get_containers_for_evaluation_object(context, sites=None, include_question_sets=False):
    """
    For the given evaluation object, fetch all assignments/surveys which
    contain it. `question_sets` toggles whether containing question sets are
    also returned. We do not exclude question sets included in assignments.
    """
    if IQAssignment.providedBy(context):  # check itself
        return (context,)
    if isinstance(context, six.string_types):
        ntiid = context
    else:
        ntiid = context.ntiid
    contained = (ntiid,)

    mime_types = list(ALL_ASSIGNMENT_MIME_TYPES)
    mime_types.append(SURVEY_MIME_TYPE)
    if include_question_sets:
        mime_types.extend((QUESTION_SET_MIME_TYPE, QUESTION_BANK_MIME_TYPE))

    sites = get_component_hierarchy_names() if not sites else sites
    sites = sites.split() if isinstance(sites, six.string_types) else sites
    query = {
        IX_SITE: {'any_of': sites},
        IX_CONTAINMENT: {'any_of': contained},
        IX_ASSESS_MIMETYPE: {'any_of': mime_types}
    }

    result = []
    catalog = get_evaluation_catalog()
    intids = component.getUtility(IIntIds)
    for uid in catalog.apply(query) or ():
        evaluation = intids.queryObject(uid)
        if IQEvaluation.providedBy(evaluation):  # extra check
            result.append(evaluation)
    return tuple(result)


def get_available_assignments_for_evaluation_object(context):
    """
    For the given evaluation object, fetch all currently available assignments
    containing the object.
    """
    results = []
    assignments = get_containers_for_evaluation_object(context)
    for assignment in assignments or ():
        if is_assignment_available(assignment):
            results.append(assignment)
    return results


def is_assignment_available(assignment, course=None, user=None):
    """
    For the given assignment, determines if it is published and
    available via the assignment policy.
    """
    result = False
    if not is_published(assignment):
        return result
    user = get_remote_user() if user is None else User
    if course is None:
        course = find_course_for_assignment(assignment, user, exc=False)
    start_date = get_available_for_submission_beginning(assignment, course)
    if not start_date or start_date < datetime.utcnow():
        result = True
    return result


def is_assignment_available_for_submission(assignment, course, user=None):
    """
    For the given assignment, determines if it is available for submission
    via the assignment policy.

    This includes:

    * assignment is open for submission
    * assignment is not already completed (successfully) by user
    * it is not past the submission buffer
    * the instructor has not supplied a grade (placeholder submission)
    """
    if not is_assignment_available(assignment, course, user):
        return False
    result = True
    end_date = get_available_for_submission_ending(assignment, course)
    submission_buffer = get_policy_field(assignment, course, 'submission_buffer', default=None)
    # Past submission buffer
    if end_date and submission_buffer is not None:
        submission_buffer = int(submission_buffer)
        cutoff_date = end_date + timedelta(seconds=submission_buffer)
        result = datetime.utcnow() < cutoff_date
    # Successfully completed
    if result:
        completed_item = get_completed_item(user, course, assignment)
        result = completed_item is None or not completed_item.Success
    # Placeholder submission
    if result:
        container = component.queryMultiAdapter((course, user),
                                                IUsersCourseAssignmentHistory)
        if container is not None:
            submission_container = container.get(assignment.ntiid)
            if submission_container:
                # This *should* only be the first item, if any.
                for history_item in submission_container.values():
                    if IPlaceholderAssignmentSubmission.providedBy(history_item.Submission):
                        result = False
                        break
    return result


def get_max_time_allowed(assignment, course):
    """
    For a given IQTimedAssignment and course, return the maximum time allowed to
    take the assignment, defined by the assignment policies.
    """
    max_time_allowed = assignment.maximum_time_allowed
    policy_max_time = get_policy_field(assignment, course,
                                       'maximum_time_allowed')
    if      policy_max_time \
        and policy_max_time != max_time_allowed:
        max_time_allowed = policy_max_time
    return max_time_allowed


def is_discussion_assignment_non_public(assignment):
    """
    Check if the discussion target of an :class:`IQDiscussionAssignment`
    points to a discussion visible to non-public users only.
    """
    is_non_public = False
    if      IQEditableEvaluation.providedBy(assignment) \
        and IQDiscussionAssignment.providedBy(assignment):
        course = find_interface(assignment, ICourseInstance, strict=False)
        topic = find_object_with_ntiid(assignment.discussion_ntiid)
        if course is not None and topic is not None:
            if ICourseDiscussion.providedBy(topic):
                scopes = get_implied_by_scopes(topic.scopes)
                is_non_public = not ES_ALL in scopes and not ES_PUBLIC in scopes
            elif ITopic.providedBy(topic):
                public_scope = course.SharingScopes[ES_PUBLIC]
                is_non_public = not topic.isSharedWith(public_scope)
    return is_non_public


def is_assignment_non_public_only(context):
    """
    For the given assignment, return if it should be non-public only.
    """
    # We used to check course non-public status, but some courses are
    # only available by invitation only. Thus, we only can designate
    # non-public only if we point to a non-public discussion as a
    # dicsussion assignment.
    return is_discussion_assignment_non_public(context)


def is_global_evaluation(evaluation):
    """
    Returns whether the given evaluation is from a global content-package/course.
    """
    package = find_interface(evaluation, IContentPackage, strict=False)
    library = find_interface(evaluation, IContentPackageLibrary, strict=False)
    return IGlobalContentPackage.providedBy(package) \
        or IGlobalContentPackageLibrary.providedBy(library)
