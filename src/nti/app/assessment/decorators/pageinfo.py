#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from urllib import unquote

from zope import component
from zope import interface

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.app.products.courseware.utils import is_enrolled
from nti.app.products.courseware.utils import is_course_instructor

from nti.appserver.interfaces import IContentUnitInfo

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet 
from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.ntiids.ntiids import is_valid_ntiid_string
from nti.ntiids.ntiids import find_object_with_ntiid

from .._utils import check_assessment
from .._utils import copy_questionset
from .._utils import copy_questionbank

from ..common import get_assessment_items_from_unit
from ..common import AssessmentItemProxy as AssignmentProxy

from ..interfaces import get_course_assignment_predicate_for_user
				
@interface.implementer(IExternalMappingDecorator)
@component.adapter(IContentUnitInfo)
class _ContentUnitAssessmentItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result_map):
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self,context,result_map)
				and context.contentUnit is not None)
			
	def _get_course(self, contentUnit, user):
		result = None
		course_id = self.request.params.get('course')
		course_id = unquote(course_id) if course_id else None
		if course_id and is_valid_ntiid_string(course_id):
			result = find_object_with_ntiid(course_id)
			result = ICourseInstance(result, None)
			if result is not None:
				## CS: make sure the user is either enrolled or is an instructor in the 
				## course passed as parameter
				if not (is_enrolled(result, user) or is_course_instructor(result, user)):
					result = None
		if result is None:
			result = component.queryMultiAdapter((contentUnit, user), ICourseInstance)	
		return result		 
	
	def _do_decorate_external( self, context, result_map ):
		entry_ntiid = None
		qsids_to_strip = set()
		assignment_predicate = None
		
		# When we return page info, we return questions
		# for all of the embedded units as well
		result = get_assessment_items_from_unit(context.contentUnit)
		
		# Filter out things they aren't supposed to see...currently only
		# assignments...we can only do this if we have a user and a course
		user = self.remoteUser
		course = self._get_course(context.contentUnit, user)
		if course is not None:
			# Only things in context of a course should have assignments
			assignment_predicate = get_course_assignment_predicate_for_user(user, course)
			entry_ntiid = getattr(ICourseCatalogEntry(course, None), 'ntiid', None)

		new_result = {}
		is_instructor = False if course is None else is_course_instructor(course, user)
		for ntiid, x in result.iteritems():
			
			# To keep size down, when we send back assignments or question sets,
			# we don't send back the things they contain as top-level. Moreover,
			# for assignments we need to apply a visibility predicate to the assignment
			# itself.
			
			if IQuestionBank.providedBy(x):
				x = copy_questionbank(x, is_instructor, qsids_to_strip)
				x.ntiid = ntiid
				new_result[ntiid] = x 
			elif IRandomizedQuestionSet.providedBy(x):
				x = x if not is_instructor else copy_questionset(x, True)
				x.ntiid = ntiid
				new_result[ntiid] = x 
			elif IQuestionSet.providedBy(x):
				new_result[ntiid] = x
			elif IQSurvey.providedBy(x):
				new_result[ntiid] = x
				for poll in x.questions:
					qsids_to_strip.add(poll.ntiid)
			elif IQAssignment.providedBy(x):
				if assignment_predicate is None:
					logger.warn("Found assignment (%s) outside of course context "
								"in %s; dropping", x, context.contentUnit)
				elif assignment_predicate(x):
					# Yay, keep the assignment
					x = check_assessment(x, user, is_instructor)
					x = AssignmentProxy(x, entry_ntiid)
					new_result[ntiid] = x
				
				# But in all cases, don't echo back the things
				# it contains as top-level items.
				# We are assuming that these are on the same page
				# for now and that they are only referenced by
				# this assignment. # XXX FIXME: Bad limitation
				for assignment_part in x.parts:
					question_set = assignment_part.question_set
					qsids_to_strip.add(question_set.ntiid)
					for question in question_set.questions:
						qsids_to_strip.add(question.ntiid)
			else:
				new_result[ntiid] = x

		for bad_ntiid in qsids_to_strip:
			new_result.pop(bad_ntiid, None)
		result = new_result.values()

		if result:
			ext_items = to_external_object(result)
			result_map['AssessmentItems'] = ext_items
