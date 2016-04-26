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

from zope import component

from zope.intid.interfaces import IIntIds

from zope.proxy import isProxy
from zope.proxy import ProxyBase

from zope.schema.interfaces import RequiredMissing

from nti.app.assessment import get_evaluation_catalog
from nti.app.assessment import get_submission_catalog

from nti.app.assessment.assignment_filters import AssessmentPolicyExclusionFilter

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import IX_SUBMITTED
from nti.app.assessment.index import IX_CONTAINERS
from nti.app.assessment.index import IX_CONTAINMENT
from nti.app.assessment.index import IX_ASSESSMENT_ID
from nti.app.assessment.index import IX_MIMETYPE as IX_ASSESS_MIMETYPE

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints

from nti.assessment.interfaces import NTIID_TYPE
from nti.assessment.interfaces import DISCLOSURE_NEVER
from nti.assessment.interfaces import DISCLOSURE_ALWAYS
from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQAggregatedInquiry
from nti.assessment.interfaces import IQInquirySubmission
from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.time import time_to_64bit_int

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.legacy_catalog import ICourseCatalogLegacyEntry

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.coremetadata.interfaces import IRecordable
from nti.coremetadata.interfaces import SYSTEM_USER_ID

from nti.dataserver.metadata_index import IX_MIMETYPE
from nti.dataserver.metadata_index import IX_CONTAINERID

from nti.metadata import dataserver_metadata_catalog

from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import get_provider
from nti.ntiids.ntiids import get_specific
from nti.ntiids.ntiids import make_specific_safe
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.interfaces import IHostPolicyFolder

from nti.site.site import get_component_hierarchy_names

from nti.traversal.traversal import find_interface

from nti.zope_catalog.catalog import ResultSet

NAQ = NTIID_TYPE

def get_resource_site_name(context):
	folder = find_interface(context, IHostPolicyFolder, strict=False)
	return folder.__name__ if folder is not None else None
get_course_site = get_resource_site_name

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
	return tuple(result)

def get_evaluation_containers(evaluation):
	result = []
	catalog = get_evaluation_catalog()
	for ntiid in catalog.get_containers(evaluation):
		container = find_object_with_ntiid(ntiid) if ntiid else None
		if container is not None:
			result.append(container)
	return tuple(result)

def get_evaluation_courses(evaluation):
	result = []
	for container in get_evaluation_containers(evaluation):
		if		ICourseInstance.providedBy(container) \
			or	ICourseCatalogEntry.providedBy(container):
			result.append(ICourseInstance(container))
	return result

def get_course_evaluations(context, sites=None, intids=None, mimetypes=None):
	if isinstance(context, six.string_types):
		ntiid = context
	else:
		course = ICourseInstance(context)
		entry = ICourseCatalogEntry( course )
		if ICourseCatalogLegacyEntry.providedBy( entry ):
			# Global courses cannot use index.
			return get_course_assessment_items( course )
		ntiid = entry.ntiid
		sites = get_course_site(course) if not sites else sites
	sites = get_component_hierarchy_names() if not sites else sites
	sites = sites.split() if isinstance(sites, six.string_types) else sites
	query = {
		IX_SITE: {'any_of': sites},
		IX_CONTAINERS: {'any_of': (ntiid,)},
	}
	mimetypes = mimetypes.split() if isinstance(mimetypes, six.string_types) else mimetypes
	if mimetypes:
		query[IX_ASSESS_MIMETYPE] = {'any_of' : mimetypes }

	result = []
	catalog = get_evaluation_catalog()
	intids = component.getUtility(IIntIds) if intids is None else intids
	for uid in catalog.apply(query) or ():
		evaluation = intids.queryObject(uid)
		if not mimetypes or IQEvaluation.providedBy(evaluation): # extra check
			result.append(evaluation)
	return tuple(result)

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
	item = item if isProxy(item, AssessmentItemProxy) else AssessmentItemProxy(item)
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
			for child in unit.children:
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

def is_locked(assesment):
	return IRecordable.providedBy(assesment) and assesment.locked

def get_available_for_submission_beginning(assesment, context=None):
	course = ICourseInstance(context, None)
	# Use our assignment policy if not locked.
	if course is not None and not is_locked(assesment):
		dates = IQAssessmentDateContext(course)
		result = dates.of(assesment).available_for_submission_beginning
	else:
		result = assesment.available_for_submission_beginning
	return result

def get_available_for_submission_ending(assesment, context=None):
	course = ICourseInstance(context, None)
	# Use our assignment policy if not locked.
	if course is not None and not is_locked(assesment):
		dates = IQAssessmentDateContext(course)
		result = dates.of(assesment).available_for_submission_ending
	else:
		result = assesment.available_for_submission_ending
	return result

# assignment

def find_course_for_assignment(assignment, user, exc=True):
	# Check that they're enrolled in the course that has the assignment
	course = component.queryMultiAdapter((assignment, user), ICourseInstance)
	if course is None:
		# For BWC, we also check to see if we can just get
		# one based on the content package of the assignment, not
		# checking enrollment.
		# TODO: Drop this
		package = find_interface(assignment, IContentPackage, strict=False)
		course = ICourseInstance(package, None)
		if course is not None:
			logger.debug("No enrollment found, assuming generic course. Tests only?")

	# If one does not exist, we cannot grade because we have nowhere
	# to dispatch to.
	if course is None and exc:
		raise RequiredMissing("Course cannot be found")

	return course

def get_course_from_assignment(assignment, user=None, catalog=None,
							   registry=component, exc=False):
	# check if we have the context catalog entry we can use
	# as reference (.AssessmentItemProxy) this way
	# instructor can find the correct course when they are looking at a section.
	result = None
	catalog = catalog if catalog is not None else registry.getUtility(ICourseCatalog)
	try:
		ntiid = assignment.CatalogEntryNTIID or u''
		entry = find_object_with_ntiid(ntiid)
		if entry is None:
			entry = catalog.getCatalogEntry(ntiid)
		result = ICourseInstance(entry, None)
	except (KeyError, AttributeError):
		pass

	if result is None:
		courses = get_evaluation_courses(assignment)
		result = courses[0] if len(courses) == 1 else None

	# could not find a course .. try adapter
	if result is None and user is not None:
		result = find_course_for_assignment(assignment, user, exc=exc)
	return result

def has_assigments_submitted(context, user):
	course = ICourseInstance(context, None)
	histories = component.queryMultiAdapter((course, user),
											IUsersCourseAssignmentHistory)
	result = histories is not None and len(histories) > 0
	return result

def get_assessment_metadata_item(context, user, assignment):
	course = ICourseInstance(context, None)
	metadata = component.queryMultiAdapter((course, user),
											IUsersCourseAssignmentMetadata)
	if metadata is not None:
		ntiid = assignment.ntiid if IQAssignment.providedBy(assignment) else str(assignment)
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

def get_course_assignments(context, sort=True, reverse=False, do_filtering=True):
	items = get_course_evaluations(context, mimetypes=ASSIGNMENT_MIME_TYPE)
	ntiid = getattr(ICourseCatalogEntry(context, None), 'ntiid', None)
	if do_filtering:
		# Filter out excluded assignments so they don't show in the gradebook either
		course = ICourseInstance(context)
		_filter = AssessmentPolicyExclusionFilter(course=course)
		assignments = [ proxy(x, catalog_entry=ntiid) for x in items
			 	  		if 		IQAssignment.providedBy(x) \
			 	  			and x.is_published() \
			 	  			and _filter.allow_assessment_for_user_in_course(x, course=course) ]
	else:
		assignments = [	proxy(x, catalog_entry=ntiid)
						for x in items if IQAssignment.providedBy(x)]
	if sort:
		assignments = sorted(assignments, cmp=assignment_comparator, reverse=reverse)
	return assignments

def get_course_self_assessments(context):
	"""
	Given an :class:`.ICourseInstance`, return a list of all
	the \"self assessments\" in the course. Self-assessments are
	defined as top-level question sets that are not used within an assignment
	in the course.
	"""
	result = list()
	qsids_to_strip = set()
	items = get_course_evaluations(context,
								   mimetypes=(QUESTION_SET_MIME_TYPE, ASSIGNMENT_MIME_TYPE))

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
	# check if we have the context catalog entry we can use
	# as reference (.AssessmentItemProxy)
	result = None
	try:
		ntiid = inquiry.CatalogEntryNTIID
		context = find_object_with_ntiid(ntiid or u'')
		result = ICourseInstance(context, None)
	except (KeyError, AttributeError):
		pass

	# could not find a course .. try adapter
	if result is None and user is not None:
		result = find_course_for_inquiry(inquiry, user, exc=exc)
	return result

def get_course_inquiries(context, do_filtering=True):
	items = get_course_evaluations(context)
	ntiid = ICourseCatalogEntry(context).ntiid
	if do_filtering:
		# Filter out excluded assignments so they don't show in the gradebook either
		course = ICourseInstance(context)
		_filter = AssessmentPolicyExclusionFilter(course=course)
		surveys = [ proxy(x, catalog_entry=ntiid) for x in items
			 	  	if 		IQInquiry.providedBy(x) \
			 	  		and x.is_published() \
			 	  		and _filter.allow_assessment_for_user_in_course(x, course=course) ]
	else:
		surveys = [	proxy(x, catalog_entry=ntiid) 
					for x in items if IQInquiry.providedBy(x) ]
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
	course = ICourseInstance(context)
	if subinstances:
		courses = get_course_hierarchy(course)
	else:
		courses = (course,)
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
	ntiids = {getattr(ICourseCatalogEntry(x, None), 'ntiid', None) for x in courses}
	ntiids.discard(None)
	return ntiids

def has_savepoints(context, courses=()):
	context_ntiid = getattr(context, 'ntiid', context)
	for course in to_course_list(courses) or ():
		savepoints = IUsersCourseAssignmentSavepoints(course, None)
		if savepoints is not None and savepoints.has_assignment(context_ntiid):
			return True
	return False

def get_submissions(context, courses=(), index_name=IX_ASSESSMENT_ID):
	courses = to_course_list(courses)
	if not courses:
		return ()
	else:
		catalog = get_submission_catalog()
		intids = component.getUtility(IIntIds)
		entry_ntiids = get_entry_ntiids(courses)
		sites = {get_resource_site_name(x) for x in courses}
		context_ntiid = getattr(context, 'ntiid', context)
		query = {
		 	IX_SITE: {'any_of':sites},
			IX_COURSE: {'any_of':entry_ntiids},
		 	index_name: {'any_of':(context_ntiid,)}
		}
		uids = catalog.apply(query) or ()
		return ResultSet(uids, intids, True)

def has_submissions(context, courses=()):
	for _ in get_submissions(context, courses):
		return True
	return False

def evaluation_submissions(context, course, subinstances=True):
	course = ICourseInstance(course)
	result = get_submissions(context,
							 index_name=IX_SUBMITTED,
							 courses=get_courses(course, subinstances=subinstances))
	return result

def inquiry_submissions(context, course, subinstances=True):
	course = ICourseInstance(course)
	result = get_submissions(context,
							 index_name=IX_ASSESSMENT_ID,
							 courses=get_courses(course, subinstances=subinstances))
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
	catalog = dataserver_metadata_catalog()
	intids = component.getUtility(IIntIds)
	query = {
		IX_MIMETYPE: {'any_of':(mimeType,)},
		IX_CONTAINERID: {'any_of':(containerId,)}
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

def get_max_time_allowed(assignment, course):
	"""
	For a given IQTimedAssignment and course, return the maximum time allowed to
	take the assignment, definied by the assignment policies.
	"""
	max_time_allowed = assignment.maximum_time_allowed
	policy = IQAssignmentPolicies(course).getPolicyForAssignment(assignment.ntiid)
	if 		policy \
		and 'maximum_time_allowed' in policy \
		and policy['maximum_time_allowed'] != max_time_allowed:
		max_time_allowed = policy['maximum_time_allowed']
	return max_time_allowed

def make_evaluation_ntiid(kind, creator=SYSTEM_USER_ID, base=None, extra=None):
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

	current_time = time_to_64bit_int(time.time())
	creator = getattr(creator, 'username', creator)
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
