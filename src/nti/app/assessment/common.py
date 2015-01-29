#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope.schema.interfaces import RequiredMissing

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.traversal import find_interface
		
from .interfaces import ICourseAssignmentCatalog
from .interfaces import ICourseAssessmentItemCatalog
from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentMetadata

from .assignment_filters import AssignmentPolicyExclusionFilter

def same_content_unit_file(unit1, unit2):
	try:
		return unit1.filename.split('#',1)[0] == unit2.filename.split('#',1)[0]
	except (AttributeError, IndexError):
		return False
	
def get_assessment_items_from_unit(contentUnit):
	
	def recur(unit, accum):
		if same_content_unit_file(unit, contentUnit):
			try:
				qs = IQAssessmentItemContainer(unit, ())
			except TypeError:
				qs = ()

			accum.update( {q.ntiid: q for q in qs} )

			for child in unit.children:
				recur( child, accum )
	
	result = dict()
	recur(contentUnit, result )
	return result

def find_course_for_assignment(assignment, user, exc=True):
	# Check that they're enrolled in the course that has the assignment
	course = component.queryMultiAdapter( (assignment, user),
										  ICourseInstance)
	if course is None:
		# For BWC, we also check to see if we can just get
		# one based on the content package of the assignment, not
		# checking enrollment.
		# TODO: Drop this
		course = ICourseInstance( find_interface(assignment, IContentPackage, strict=False),
								  None)
		if course is not None:
			logger.warning("No enrollment found, assuming generic course. Tests only?")

	# If one does not exist, we cannot grade because we have nowhere
	# to dispatch to.
	if course is None and exc:
		raise RequiredMissing("Course cannot be found")

	return course

def has_assigments_submitted(course, user):
	histories = component.queryMultiAdapter((course, user),
											IUsersCourseAssignmentHistory )
	return histories is not None and len(histories) > 0

def get_assessment_metadata_item(course, user, assignment):
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

def get_course_assignment_items(course, sort=True, reverse=False):
	course = ICourseInstance(course)
	item_catalog = ICourseAssessmentItemCatalog(course)
	result = [x for x in item_catalog.iter_assessment_items()]
	return result

def get_course_assignments(course, sort=True, reverse=False, do_filtering=True):
	# Filter out excluded assignments so they don't show in the gradebook either
	course = ICourseInstance(course)
	assignment_catalog = ICourseAssignmentCatalog(course)
	if do_filtering:
		_filter = AssignmentPolicyExclusionFilter(course=course)
		assignments = [x for x in assignment_catalog.iter_assignments()
			 	  	   if _filter.allow_assignment_for_user_in_course(x, course=course)]
	else:
		assignments = [x for x in assignment_catalog.iter_assignments()]
	if sort:
		assignments = sorted(assignments, cmp=assignment_comparator, reverse=reverse)
	return assignments
