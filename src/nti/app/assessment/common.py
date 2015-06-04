#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component

from zope.proxy import ProxyBase

from zope.schema.interfaces import RequiredMissing

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.traversal.traversal import find_interface

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentMetadata

from .assignment_filters import AssignmentPolicyExclusionFilter

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
	item = item if type(item) == AssessmentItemProxy else AssessmentItemProxy(item)
	item.ContentUnitNTIID = content_unit or item.ContentUnitNTIID
	item.CatalogEntryNTIID = catalog_entry or item.CatalogEntryNTIID
	return item

def same_content_unit_file(unit1, unit2):
	try:
		return unit1.filename.split('#', 1)[0] == unit2.filename.split('#', 1)[0]
	except (AttributeError, IndexError):
		return False

def get_assessment_items_from_unit(contentUnit):

	def recur(unit, accum):
		if same_content_unit_file(unit, contentUnit):
			try:
				qs = IQAssessmentItemContainer(unit, ())
			except TypeError:
				qs = ()

			accum.update({q.ntiid: q for q in qs})

			for child in unit.children:
				recur(child, accum)

	result = dict()
	recur(contentUnit, result)
	return result

def get_course_packages(context):
	context = ICourseInstance(context)
	# We have now a specific interface for courses that
	# are tied to content: IContentCourseInstance; they have
	# the ContentBundle attribute.
	# However, we still have the LegacyCommunityBasedCourseInstances
	# to deal with that have one content package; it's easiest
	# to support both types in one single place.
	packages = ()
	try:
		packages = context.ContentPackageBundle.ContentPackages
	except AttributeError:
		# Ok, the old legacy case
		packages = (context.legacy_content_package,)
	return packages

def get_content_packages_assessment_items(package):
	result = []
	def _recur(unit):
		items = IQAssessmentItemContainer(unit, ())
		for item in items:
			item = proxy(item, content_unit=unit.ntiid)
			result.append(item)
		for child in unit.children:
			_recur(child)
	_recur(package)
	# On py3.3, can easily 'yield from' nested generators
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
	return assessments

# assignment

def find_course_for_assignment(assignment, user, exc=True):
	# Check that they're enrolled in the course that has the assignment
	course = component.queryMultiAdapter((assignment, user), ICourseInstance)
	if course is None:
		# For BWC, we also check to see if we can just get
		# one based on the content package of the assignment, not
		# checking enrollment.
		# TODO: Drop this
		course = ICourseInstance(find_interface(assignment, IContentPackage, strict=False),
								  None)
		if course is not None:
			logger.warning("No enrollment found, assuming generic course. Tests only?")

	# If one does not exist, we cannot grade because we have nowhere
	# to dispatch to.
	if course is None and exc:
		raise RequiredMissing("Course cannot be found")

	return course

def get_course_from_assignment(assignment, user=None, catalog=None, registry=component,
							   exc=False):
	# # check if we have the context catalog entry we can use
	# # as reference (.AssessmentItemProxy) this way
	# # instructor can find the correct course when they are looking at a section.
	result = None
	try:
		ntiid = assignment.CatalogEntryNTIID
		catalog = catalog if catalog is not None else registry.getUtility(ICourseCatalog)
		entry = catalog.getCatalogEntry(ntiid) if ntiid else None
		result = ICourseInstance(entry, None)
	except (KeyError, AttributeError):
		pass

	# # could not find a course .. try adapter
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
	items = get_course_assessment_items(context) or ()
	ntiid = getattr(ICourseCatalogEntry(context, None), 'ntiid', None)
	if do_filtering:
		# Filter out excluded assignments so they don't show in the gradebook either
		course = ICourseInstance(context)
		_filter = AssignmentPolicyExclusionFilter(course=course)
		assignments = [ proxy(x, catalog_entry=ntiid) for x in items
			 	  		if IQAssignment.providedBy(x) and \
			 	  	   	   _filter.allow_assignment_for_user_in_course(x, course=course)]
	else:
		assignments = [	proxy(x, catalog_entry=ntiid)
						for x in items if IQAssignment.providedBy(x)]
	if sort:
		assignments = sorted(assignments, cmp=assignment_comparator, reverse=reverse)
	return assignments

# surveys

def find_course_for_inquiry(inquiry, user, exc=True):
	# Check that they're enrolled in the course that has the inquiry
	course = component.queryMultiAdapter((inquiry, user), ICourseInstance)
	if course is None and exc:
		raise RequiredMissing("Course cannot be found")
	return course

def get_course_from_inquiry(inquiry, user=None, catalog=None, registry=component, exc=False):
	# check if we have the context catalog entry we can use
	# as reference (.AssessmentItemProxy)
	result = None
	try:
		ntiid = inquiry.CatalogEntryNTIID
		catalog = catalog if catalog is not None else registry.getUtility(ICourseCatalog)
		entry = catalog.getCatalogEntry(ntiid) if ntiid else None
		result = ICourseInstance(entry, None)
	except (KeyError, AttributeError):
		pass

	# could not find a course .. try adapter
	if result is None and user is not None:
		result = find_course_for_inquiry(inquiry, user, exc=exc)
	return result

def get_course_inquiries(context):
	items = get_course_assessment_items(context)
	ntiid = getattr(ICourseCatalogEntry(context, None), 'ntiid', None)
	surveys = [proxy(x, catalog_entry=ntiid) for x in items if IQInquiry.providedBy(x)]
	return surveys
