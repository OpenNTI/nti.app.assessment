#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import time
import itertools

from datetime import datetime

from requests.structures import CaseInsensitiveDict

from zope import component
from zope import lifecycleevent

from zope.event import notify

from zope.intid.interfaces import IIntIds

from zope.proxy import isProxy
from zope.proxy import ProxyBase

from zope.schema.interfaces import RequiredMissing

from zope.security.interfaces import IPrincipal

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from ZODB import loglevels

from persistent.list import PersistentList

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.assignment_filters import AssessmentPolicyExclusionFilter

from nti.app.assessment.common.assessed import reassess_assignment_history_item

from nti.app.assessment.common.hostpolicy import get_resource_site_name

from nti.app.assessment.evaluations import raise_error

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import IX_SUBMITTED
from nti.app.assessment.index import IX_CONTAINERS
from nti.app.assessment.index import IX_CONTAINMENT
from nti.app.assessment.index import IX_ASSESSMENT_ID
from nti.app.assessment.index import IX_MIMETYPE as IX_ASSESS_MIMETYPE

from nti.app.assessment.index import get_evaluation_catalog
from nti.app.assessment.index import get_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseSubmissionItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.app.assessment.interfaces import ObjectRegradeEvent

from nti.app.authentication import get_remote_user

from nti.app.externalization.error import raise_json_error

from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment

from nti.assessment.common import can_be_auto_graded

from nti.assessment.interfaces import NTIID_TYPE
from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import DISCLOSURE_NEVER
from nti.assessment.interfaces import DISCLOSURE_ALWAYS
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE
from nti.assessment.interfaces import QUESTION_BANK_MIME_TYPE
from nti.assessment.interfaces import ALL_ASSIGNMENT_MIME_TYPES

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQAggregatedInquiry
from nti.assessment.interfaces import IQInquirySubmission
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQDiscussionAssignment
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IGlobalContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IGlobalContentPackageLibrary

from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussion

from nti.contenttypes.courses.discussions.utils import get_implied_by_scopes

from nti.contenttypes.courses.interfaces import ES_ALL
from nti.contenttypes.courses.interfaces import ES_PUBLIC

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSubInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import IDenyOpenEnrollment
from nti.contenttypes.courses.interfaces import INonPublicCourseInstance

from nti.contenttypes.courses.legacy_catalog import ILegacyCourseInstance

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.utils import get_parent_course
from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.coremetadata.interfaces import SYSTEM_USER_NAME

from nti.dataserver.contenttypes.forums.interfaces import ITopic

from nti.dataserver.interfaces import IUser

from nti.dataserver.metadata.index import IX_MIMETYPE
from nti.dataserver.metadata.index import IX_CONTAINERID

from nti.dataserver.metadata.index import get_metadata_catalog

from nti.dataserver.users import User

from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import StandardExternalFields

from nti.links.links import Link

from nti.namedfile.interfaces import INamedFile

from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import get_provider
from nti.ntiids.ntiids import get_specific
from nti.ntiids.ntiids import make_specific_safe
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.publishing.interfaces import IPublishable

from nti.site.interfaces import IHostPolicyFolder

from nti.site.site import get_component_hierarchy_names

from nti.traversal.traversal import find_interface

from nti.zodb.containers import time_to_64bit_int

from nti.zope_catalog.catalog import ResultSet

NAQ = NTIID_TYPE

CLASS = StandardExternalFields.CLASS
LINKS = StandardExternalFields.LINKS
MIME_TYPE = StandardExternalFields.MIMETYPE

UNGRADABLE_CODE = u'UngradableInAutoGradeAssignment'
UNGRADABLE_MSG = _("Ungradable item in auto-graded assignment.")

DISABLE_AUTO_GRADE_MSG = _("Removing points to auto-gradable assignment. Do you want to disable auto-grading?")

AUTO_GRADE_NO_POINTS_MSG = _("Cannot enable auto-grading without setting a point value.")


def get_user(user=None, remote=False, request=None):
    if user is None and remote:
        user = get_remote_user(request)
    elif IPrincipal.providedBy(user):
        user = user.id
    if user is not None and not IUser.providedBy(user):
        user = User.get_user(str(user))
    return user


# containment


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


def get_evaluation_courses(evaluation):
    result = []
    for container in get_evaluation_containers(evaluation):
        if     ICourseInstance.providedBy(container) \
            or ICourseCatalogEntry.providedBy(container):
            result.append(ICourseInstance(container))
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
        sites = get_resource_site_name(course) if not sites else sites

    return get_container_evaluations(containers,
                                     sites=sites,
                                     intids=intids,
                                     mimetypes=mimetypes)

# assessment


class AssessmentItemProxy(ProxyBase):

    ContentUnitNTIID = property(
        lambda s: s.__dict__.get('_v_content_unit'),
        lambda s, v: s.__dict__.__setitem__('_v_content_unit', v))

    CatalogEntryNTIID = property(
        lambda s: s.__dict__.get('_v_catalog_entry'),
        lambda s, v: s.__dict__.__setitem__('_v_catalog_entry', v))

    def __new__(cls, base, *args, **kwargs):
        return ProxyBase.__new__(cls, base)

    def __init__(self, base, content_unit=None, catalog_entry=None):
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
    try:
        result = IQAssessmentItemContainer(unit).assessments()
    except TypeError:
        result = ()
    return result


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


def get_policy_for_assessment(asm_id, context):
    course = ICourseInstance(context)
    policies = IQAssessmentPolicies(course)
    policy = policies.getPolicyForAssessment(asm_id)
    return policy


def get_available_for_submission_beginning(assesment, context=None):
    course = ICourseInstance(context, None)
    dates = IQAssessmentDateContext(course, None)
    if dates is not None:
        result = dates.of(assesment).available_for_submission_beginning
    else:
        # No policy, pull from object.
        result = assesment.available_for_submission_beginning
    return result


def get_available_for_submission_ending(assesment, context=None):
    course = ICourseInstance(context, None)
    dates = IQAssessmentDateContext(course, None)
    if dates is not None:
        result = dates.of(assesment).available_for_submission_ending
    else:
        # No policy, pull from object.
        result = assesment.available_for_submission_ending
    return result

# assignment


def find_course_for_evaluation(evaluation, user, exc=True):
    # Check that they're enrolled in the course that has the assignment
    course = component.queryMultiAdapter((evaluation, user), ICourseInstance)
    if course is None:
        # For BWC, we also check to see if we can just get
        # one based on the content package of the assignment, not
        # checking enrollment.
        # TODO: Drop this
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


def _get_evaluation_catalog_entry(evaluation, catalog=None, registry=component):
    # check if we have the context catalog entry we can use
    # as reference (.AssessmentItemProxy) this way
    # instructor can find the correct course when they are looking at a
    # section.
    result = None
    if catalog is None:
        catalog = registry.getUtility(ICourseCatalog)
    try:
        ntiid = evaluation.CatalogEntryNTIID or u''
        result =  find_object_with_ntiid(ntiid) \
               or catalog.getCatalogEntry(ntiid)
    except (KeyError, AttributeError):
        pass
    return result


def get_course_from_evaluation(evaluation, user=None, catalog=None,
                               registry=component, exc=False):
    entry = _get_evaluation_catalog_entry(evaluation, catalog, registry)
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


def get_assessment_metadata_item(context, user, assignment):
    course = ICourseInstance(context, None)
    metadata = component.queryMultiAdapter((course, user),
                                           IUsersCourseAssignmentMetadata)
    if metadata is not None:
        if IQAssignment.providedBy(assignment):
            ntiid = assignment.ntiid
        else:
            ntiid = str(assignment)
        if ntiid in metadata:
            return metadata[ntiid]
    return None


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
                                          do_filtering=False, parent_course=True)
    for item in itertools.chain(package_items, course_items):
        if     not IQAssignment.providedBy(item) \
            or item.ntiid in seen:
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
        assignments = [proxy(x, catalog_entry=ntiid)
                       for x in items if IQAssignment.providedBy(x)]
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

    :param exclude_editable Exclude editable evaluations
    """
    result = list()
    qsids_to_strip = set()
    query_types = [QUESTION_SET_MIME_TYPE, QUESTION_BANK_MIME_TYPE]
    query_types.extend(ALL_ASSIGNMENT_MIME_TYPES)
    items = get_course_evaluations(context,
                                   mimetypes=query_types)

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
        elif    exclude_editable \
            and IQEditableEvaluation.providedBy(item):
            # XXX: Seems like eventually we'll want to return these.
            # We probably eventually want to mark question-sets that
            # are self-assessments.
            qsids_to_strip.add(item.ntiid)
        else:
            result.append(item)

    # Now remove the forbidden
    result = [x for x in result if x.ntiid not in qsids_to_strip]
    return result

# surveys


def find_course_for_inquiry(inquiry, user, exc=True):
    # Check that they're enrolled in the course that has the inquiry
    course = component.queryMultiAdapter((inquiry, user), ICourseInstance)
    if course is None and exc:
        raise RequiredMissing("Course cannot be found")
    return course


def get_course_from_inquiry(inquiry, user=None, registry=component, exc=False):
    result = _get_evaluation_catalog_entry(inquiry, registry=registry)
    result = ICourseInstance(result, None)

    if result is None:
        courses = get_evaluation_courses(inquiry)
        result = courses[0] if len(courses) == 1 else None

    # could not find a course .. try adapter
    if result is None and user is not None:
        result = find_course_for_inquiry(inquiry, user, exc=exc)
    return result


def get_course_inquiries(context, do_filtering=True):
    items = get_course_evaluations(context)
    ntiid = ICourseCatalogEntry(context).ntiid
    if do_filtering:
        # Filter out excluded assignments so they don't show in the gradebook
        # either
        course = ICourseInstance(context)
        _filter = AssessmentPolicyExclusionFilter(course=course)
        surveys = [proxy(x, catalog_entry=ntiid) for x in items
                   if IQInquiry.providedBy(x)
                   and _filter.allow_assessment_for_user_in_course(x, course=course)]
    else:
        surveys = [proxy(x, catalog_entry=ntiid)
                   for x in items if IQInquiry.providedBy(x)]
    return surveys


def can_disclose_inquiry(inquiry, context=None):
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
        result = not_after and datetime.utcnow() >= not_after
    return result


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
    entries = [ICourseCatalogEntry(x, None) for x in courses]
    ntiids = {x.ntiid for x in entries if x is not None}
    return ntiids


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
        assignments = get_assignments_for_evaluation_object(context)
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
    for _ in inquiry_submissions(context, course, subinstances=True):
        return True
    return False


def has_submitted_inquiry(context, user, assigment):
    user = get_user(user)
    course = ICourseInstance(context, None)
    histories = component.queryMultiAdapter((course, user),
                                            IUsersCourseInquiry)
    ntiid = getattr(assigment, 'ntiid', assigment)
    return bool(histories and ntiid in histories)


def _delete_context_contained_data(container_iface, context, course, subinstances=True):
    result = 0
    course = ICourseInstance(course)
    context_ntiid = getattr(context, 'ntiid', context)
    for course in get_courses(course, subinstances=subinstances):
        container = container_iface(course, None) or {}
        for user_data in list(container.values()):  # snapshot
            if context_ntiid in user_data:
                del user_data[context_ntiid]
                result += 1
    return result


def delete_evaluation_submissions(context, course, subinstances=True):
    result = _delete_context_contained_data(IUsersCourseAssignmentHistories,
                                            context,
                                            course,
                                            subinstances)
    return result


def delete_inquiry_submissions(context, course, subinstances=True):
    result = _delete_context_contained_data(IUsersCourseInquiries,
                                            context,
                                            course,
                                            subinstances)
    return result


def has_savepoints(context, courses=()):
    context_ntiid = getattr(context, 'ntiid', context)
    for course in to_course_list(courses) or ():
        savepoints = IUsersCourseAssignmentSavepoints(course, None)
        if savepoints is not None and savepoints.has_assignment(context_ntiid):
            return True
    return False


def delete_evaluation_savepoints(context, course, subinstances=True):
    result = _delete_context_contained_data(IUsersCourseAssignmentSavepoints,
                                            context,
                                            course,
                                            subinstances)
    return result


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


def delete_evaluation_metadata(context, course, subinstances=True):
    result = _delete_context_contained_data(IUsersCourseAssignmentMetadataContainer,
                                            context,
                                            course,
                                            subinstances)
    return result


def delete_evaluation_policies(context, course, subinstances=True):
    result = 0
    course = ICourseInstance(course)
    context_ntiid = getattr(context, 'ntiid', context)
    for course in get_courses(course, subinstances=subinstances):
        for provided in (IQAssessmentPolicies, IQAssessmentDateContext):
            container = provided(course, None) or {}
            try:
                del container[context_ntiid]
                result += 1
            except KeyError:
                pass
    return result


def delete_all_evaluation_policy_data(evaluation):
    for course in get_evaluation_courses(evaluation):
        delete_evaluation_policies(evaluation, course)


def delete_all_evaluation_data(evaluation):
    for course in get_evaluation_courses(evaluation):
        # delete policy data
        delete_evaluation_policies(evaluation, course)
        # delete submission data
        if IQInquiry.providedBy(evaluation):
            delete_inquiry_submissions(evaluation, course)
        else:
            delete_evaluation_metadata(evaluation, course)
            delete_evaluation_savepoints(evaluation, course)
            delete_evaluation_submissions(evaluation, course)


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
get_assignments_for_evaluation_object = get_containers_for_evaluation_object


def _is_published(context):
    return not IPublishable.providedBy(context) or context.is_published()


def get_available_assignments_for_evaluation_object(context):
    """
    For the given evaluation object, fetch all currently available assignments
    containing the object.
    """
    results = []
    assignments = get_assignments_for_evaluation_object(context)
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
    if not _is_published(assignment):
        return result
    user = get_remote_user() if user is None else User
    if course is None:
        course = find_course_for_assignment(assignment, user, exc=False)
    start_date = get_available_for_submission_beginning(assignment, course)
    if not start_date or start_date < datetime.utcnow():
        result = True
    return result


def get_max_time_allowed(assignment, course):
    """
    For a given IQTimedAssignment and course, return the maximum time allowed to
    take the assignment, defined by the assignment policies.
    """
    max_time_allowed = assignment.maximum_time_allowed
    policy_max_time = _get_policy_field(assignment,
                                        course,
                                        'maximum_time_allowed')
    if      policy_max_time \
        and policy_max_time != max_time_allowed:
        max_time_allowed = policy_max_time
    return max_time_allowed


def _get_policy_field(assignment, course, field):
    policy = IQAssessmentPolicies(course, None)
    assignment_ntiid = getattr(assignment, 'ntiid', assignment)
    result = policy.get(assignment_ntiid, field, False)
    return result


def get_auto_grade_policy(assignment, course):
    """
    For a given assignment (or ntiid), return the `auto_grade` policy for the given course.
    """
    return _get_policy_field(assignment, course, 'auto_grade')


def get_policy_locked(assignment, course):
    """
    For a given assignment (or ntiid), return the policy `locked` state for the given
    course.
    """
    return _get_policy_field(assignment, course, 'locked')


def get_policy_excluded(assignment, course):
    """
    For a given assignment (or ntiid), return the policy `excluded` state for the given
    course.
    """
    return _get_policy_field(assignment, course, 'excluded')


def get_auto_grade_policy_state(assignment, course):
    """
    For a given assignment (or ntiid), return the autograde state for the given course.
    """
    policy = get_auto_grade_policy(assignment, course)
    result = False
    if policy and policy.get('disable') is not None:
        # Only allow auto_grading if disable is explicitly set to False.
        result = not policy.get('disable')
    return result


def validate_auto_grade(assignment, course, request=None, challenge=False, raise_exc=True):
    """
    Validate the assignment has the proper state for auto-grading, if
    necessary. If not raising/challenging, returns a bool indicating
    whether this assignment is auto-gradable.
    """
    auto_grade = get_auto_grade_policy_state(assignment, course)
    valid_auto_grade = True
    if auto_grade:
        # Work to do
        valid_auto_grade = can_be_auto_graded(assignment)
        if not valid_auto_grade and raise_exc:
            # Probably toggling auto_grade on assignment with essays (e.g).
            if not challenge:
                request = request or get_current_request()
                raise_json_error(request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                    'message': UNGRADABLE_MSG,
                                    'code': UNGRADABLE_CODE,
                                 },
                                 None)
            # No, so inserting essay (e.g.) into autogradable.
            links = (
                Link(request.path, rel='confirm',
                     params={'overrideAutoGrade': True}, method='POST'),
            )
            raise_json_error(request,
                             hexc.HTTPConflict,
                             {
                                CLASS: 'DestructiveChallenge',
                                'message': UNGRADABLE_MSG,
                                'code': UNGRADABLE_CODE,
                                LINKS: to_external_object(links),
                                MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
                             },
                             None)
    return valid_auto_grade


def validate_auto_grade_points(assignment, course, request, externalValue):
    """
    Validate the assignment has the proper state with auto_grading and
    total_points. If removing points from auto-gradable, we challenge the
    user, disabling auto_grade upon override. If setting auto_grade without
    points, we 422.
    """
    auto_grade = get_auto_grade_policy_state(assignment, course)
    if auto_grade:
        auto_grade_policy = get_auto_grade_policy(assignment, course)
        total_points = auto_grade_policy.get('total_points')
        params = CaseInsensitiveDict(request.params)
        # Removing points while auto_grade on; challenge.
        if not total_points and 'total_points' in externalValue:
            if not params.get('disableAutoGrade'):
                links = (
                    Link(request.path, rel='confirm',
                         params={'disableAutoGrade': True}, method='PUT'),
                )
                raise_json_error(request,
                                 hexc.HTTPConflict,
                                 {
                                    CLASS: 'DestructiveChallenge',
                                    'message': DISABLE_AUTO_GRADE_MSG,
                                    'code': 'RemovingAutoGradePoints',
                                    LINKS: to_external_object(links),
                                    MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
                                 },
                                 None)
            # Disable auto grade
            auto_grade_policy['disable'] = True
        # Trying to enable auto_grade without points; 422.
        if not total_points and 'auto_grade' in externalValue:
            raise_json_error(request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': AUTO_GRADE_NO_POINTS_MSG,
                                 'code': 'AutoGradeWithoutPoints',
                             },
                             None)


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
    provider = get_provider(base) or 'NTI' if base else 'NTI'

    specific_base = get_specific(base) if base else None
    if specific_base:
        specific_base += '.%s.%s.%s' % (kind, creator, current_time)
    else:
        specific_base = '%s.%s.%s' % (kind, creator, current_time)

    if extra:
        specific_base = specific_base + ".%s" % extra
    specific = make_specific_safe(specific_base)

    ntiid = make_ntiid(nttype=NAQ,
                       base=base,
                       provider=provider,
                       specific=specific)
    return ntiid


def check_submission_version(submission, evaluation):
    """
    Make sure the submitted version matches our assignment version.
    If not, the client needs to refresh and re-submit to avoid
    submitting stale, incorrect data for this assignment.
    """
    evaluation_version = evaluation.version
    if      evaluation_version \
        and evaluation_version != getattr(submission, 'version', ''):
        raise hexc.HTTPConflict(_(u'Evaluation version has changed.'))


def pre_validate_question_change(question, externalValue):
    """
    Validate the proposed changes with the current question state
    (before modification), returning the parts that changed.
    """
    parts = externalValue.get('parts')
    check_solutions = not IQAvoidSolutionCheck.providedBy(question)
    course = find_interface(question, ICourseInstance, strict=False)
    regrade_parts = []
    if parts and has_submissions(question, course):
        for part, change in zip(question.parts, parts):
            analyzer = IQPartChangeAnalyzer(part, None)
            if analyzer is not None:
                if not analyzer.allow(change, check_solutions=check_solutions):
                    raise_error(
                        {
                            'message': _(u"Question has submissions. It cannot be updated."),
                            'code': 'CannotChangeObjectDefinition',
                        })
                if analyzer.regrade(change):
                    regrade_parts.append(part)
    return regrade_parts


def regrade_evaluation(context, course):
    result = []
    for item in evaluation_submissions(context, course):
        if IUsersCourseAssignmentHistoryItem.providedBy(item):
            logger.info('Regrading (%s) (user=%s)',
                        item.Submission.assignmentId, item.creator)
            result.append(item)
            reassess_assignment_history_item(item)
            # Now broadcast we need a new grade
            notify(ObjectRegradeEvent(item))
    return result


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


def is_assignment_non_public_only(context, courses=None):
    """
    For the given assignment, return if its courses are only
    non-public courses.
    """
    if ICourseInstance.providedBy(courses):
        courses = (courses,)
    if courses is None:
        course = get_course_from_evaluation(context)
        courses = get_courses(course)

    def _is_non_public(course):
        return INonPublicCourseInstance.providedBy( course ) \
            or IDenyOpenEnrollment.providedBy(course)

    is_non_public_only = courses and all(_is_non_public(x) for x in courses)
    is_discussion_non_public = is_discussion_assignment_non_public(context)
    return is_non_public_only or is_discussion_non_public


def get_outline_evaluation_containers(obj):
    """
    For the given evaluation, return any unique containers which might
    be found in a course outline (question sets, question banks,
    assignments, and surveys.).
    """
    if obj.ntiid is None:
        # Tests
        return
    assigment_question_sets = set()
    containers = get_containers_for_evaluation_object(obj, 
                                                      include_question_sets=True)

    # Gather assignment question sets and remove them.
    for container in containers or ():
        if IQAssignment.providedBy(container):
            assigment_question_sets.update(
                x.ntiid for x in container.iter_question_sets()
            )

    if assigment_question_sets and containers:
        results = []
        for container in containers:
            if container.ntiid not in assigment_question_sets:
                results.append(container)
    else:
        results = containers
    return results


def is_global_evaluation(evaluation):
    """
    Returns whether the given evaluation is from a global content-package/course.
    """
    package = find_interface(evaluation, IContentPackage, strict=False)
    library = find_interface(evaluation, IContentPackageLibrary, strict=False)
    return IGlobalContentPackage.providedBy(package) \
        or IGlobalContentPackageLibrary.providedBy(library)


def index_course_package_assessments(course):
    """
    Index the given course's package assessments.
    """
    catalog = get_evaluation_catalog()
    intids = component.getUtility(IIntIds)
    assessment_items = get_course_assessment_items(course)
    count = 0
    for item in assessment_items or ():
        doc_id = intids.queryId(item)
        if doc_id is not None:
            catalog.index_doc(doc_id, item)
            count += 1
    return count
