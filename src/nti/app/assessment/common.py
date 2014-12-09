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
		
from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentMetadata

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
