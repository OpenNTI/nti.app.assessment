#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import copy
from datetime import datetime

from pyramid import httpexceptions as hexc

from zope import component

from zope.event import notify as event_notify

from zope.interface.common.idatetime import IDateTime

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import validate_auto_grade
from nti.app.assessment.common import get_available_for_submission_ending
from nti.app.assessment.common import get_assignments_for_evaluation_object
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.evaluations.utils import validate_structural_edits

from nti.app.assessment.interfaces import IQPartChangeAnalyzer

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views import MessageFactory as _

from nti.app.externalization.error import raise_json_error

from nti.appserver.ugd_edit_views import UGDPutView

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import QAssessmentPoliciesModified
from nti.assessment.interfaces import QAssessmentDateContextModified

from nti.common.property import Lazy

from nti.common.string import is_true
from nti.common.string import is_false

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import SUPPORTED_DATE_KEYS

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import get_courses_for_packages

from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import StandardExternalFields

from nti.externalization.internalization import notifyModified

from nti.links.links import Link

from nti.schema.interfaces import InvalidValue

from nti.traversal.traversal import find_interface

CLASS = StandardExternalFields.CLASS
LINKS = StandardExternalFields.LINKS
NTIID = StandardExternalFields.NTIID
MIME_TYPE = StandardExternalFields.MIMETYPE

def canonicalize_question_set(self, obj, registry=component):
	obj.questions = [registry.getUtility(IQuestion, name=x.ntiid)
					 for x
					 in obj.Items]

def canonicalize_assignment(obj, registry=component):
	for part in obj.parts:
		ntiid = part.question_set.ntiid
		part.question_set = registry.getUtility(IQuestionSet, name=ntiid)
		canonicalize_question_set(part.question_set, registry)

def get_courses_from_assesment(assesment):
	course = find_interface(assesment, ICourseInstance, strict=False)
	if course is not None:
		result = (course,)
	else:
		package = find_interface(assesment, IContentPackage, strict=False)
		if package is None:
			result = ()
		else:
			result = get_courses_for_packages(packages=package.ntiid)
	return result

class AssessmentPutView(UGDPutView):

	TO_AVAILABLE_CODE = 'UnAvailableToAvailable'
	TO_UNAVAILABLE_CODE = 'AvailableToUnavailable'
	CONFIRM_CODE = 'AssessmentDateConfirm'

	TO_AVAILABLE_MSG = None
	TO_UNAVAILABLE_MSG = None
	AVAILABLE_DATE_CONFIRM_MSG = _('Are you sure you want to change the available date?')

	POLICY_KEYS = ("auto_grade", 'total_points')

	def readInput(self, value=None):
		result = UGDPutView.readInput(self, value=value)
		result.pop(NTIID, None)
		result.pop(NTIID.lower(), None)
		return result

	def _raise_conflict_error(self, code, message, course, ntiid):
		entry = ICourseCatalogEntry(course)
		logger.info('Attempting to change assignment availability (%s) (%s) (%s)',
					code,
					ntiid,
					entry.ntiid)
		links = (
			Link(self.request.path, rel='confirm',
				 params={'force':True}, method='PUT'),
		)
		raise_json_error(self.request,
						 hexc.HTTPConflict,
						 {
						 	CLASS: 'DestructiveChallenge',
							u'message': message,
							u'code': code,
							LINKS: to_external_object(links),
							MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
						 },
						 None)

	@classmethod
	def _is_date_in_range(cls, start_date, end_date, now):
		"""
		Returns if we are currently within a possibly open-ended date range.
		"""
		# Must have at least one date to be considered in-range.
		result = 	(not start_date or start_date < now) \
				and (not end_date or now < end_date)
		return bool( result )

	@classmethod
	def _start_date_available_change(cls, old_start_date, new_start_date, now):
		"""
		Returns if the start date changes availability.
		"""
		# 1. Move start date in future (old start date non-None)
		# 2. Move start date in past (new start date non-None)
		return 		old_start_date != new_start_date \
				and 	((	  new_start_date \
						  and cls._is_date_in_range(old_start_date, new_start_date, now))
					or 	(	 old_start_date \
						 and cls._is_date_in_range(new_start_date, old_start_date, now)))

	def validate_date_boundaries(self, contentObject, externalValue, courses=()):
		"""
		Validates that the assessment does not change availability states. If
		so, we throw a 409 with an available `confirm` link for user overrides.

		The webapp first publishes the assignment and passes in the availability
		dates if scheduled. If no dates are passed in (and the assignment is
		published), it is considered available.
		"""
		_marker = object()
		new_end_date = externalValue.get('available_for_submission_ending', _marker)
		new_start_date = externalValue.get('available_for_submission_beginning', _marker)
		if new_start_date is not _marker or new_end_date is not _marker:
			now = datetime.utcnow()

			try:
				if new_start_date and new_start_date is not _marker:
					new_start_date = IDateTime(new_start_date)
				if new_end_date and new_end_date is not _marker:
					new_end_date = IDateTime(new_end_date)
			except (ValueError, InvalidValue):
				# Ok, they gave us something invalid. Let our schema
				# validation handle it.
				return

			for course in courses:
				old_end_date = get_available_for_submission_ending(contentObject,
																   course)

				old_start_date = get_available_for_submission_beginning(contentObject,
																		course)

				# Use old dates if the dates are not being edited.
				if new_start_date is _marker:
					start_date_to_check = old_start_date
				else:
					start_date_to_check = new_start_date

				if new_end_date is _marker:
					end_date_to_check = old_end_date
				else:
					end_date_to_check = new_end_date

				start_date_available_change = self._start_date_available_change(old_start_date,
																				start_date_to_check, now)
				# It's currently available if published or if its
				# dates are in range.
				old_available = contentObject.isPublished() \
							and	self._is_date_in_range(old_start_date,
													   old_end_date, now)
				new_available = self._is_date_in_range(start_date_to_check,
													   end_date_to_check, now)

				# Note: we allow state to move from closed in past to
				# closed but will reopen in the future unchecked (edge case).
				if old_available and not new_available and start_date_available_change:
					# Start date made unavailable
					self._raise_conflict_error(self.TO_UNAVAILABLE_CODE,
											   self.TO_UNAVAILABLE_MSG,
											   course,
											   contentObject.ntiid)
				elif not old_available and new_available and start_date_available_change:
					# Start date made available
					self._raise_conflict_error(self.TO_AVAILABLE_CODE,
											   self.TO_AVAILABLE_MSG,
											   course,
											   contentObject.ntiid)
				elif old_available != new_available:
					# State change but not due to the start date. Give a
					# general confirmation message.
					self._raise_conflict_error(self.CONFIRM_CODE,
											   self.AVAILABLE_DATE_CONFIRM_MSG,
											   course,
											   contentObject.ntiid)

	def preflight(self, contentObject, externalValue, courses=()):
		if not self.request.params.get('force', False):
			# We do this during pre-flight because we want to compare our old
			# state versus the new.
			self.validate_date_boundaries(contentObject,
										  externalValue,
										  courses=courses)

	def validate(self, contentObject, externalValue, courses=()):
		# We could validate edits based on the unused submission/savepoint
		# code above, based on the input keys being changed.
		for course in courses:
			# Validate dates
			end_date = get_available_for_submission_ending(contentObject, course)
			start_date = get_available_for_submission_beginning(contentObject, course)
			if start_date and end_date and end_date < start_date:
				self._raise_error('AssessmentDueDateBeforeStartDate',
								  _('Due date cannot come before start date.'))
			# Validate auto_grade
			validate_auto_grade(contentObject, course)

	@property
	def policy_keys(self):
		return SUPPORTED_DATE_KEYS + self.POLICY_KEYS

	def _get_or_create_policy_part(self, course, ntiid, part=None):
		policy = result = IQAssessmentPolicies(course)
		if part:
			result = policy.get(ntiid, part)
			if not result:
				result = {}
				policy.set(ntiid, part, result)
		return result

	def _raise_error(self, code, message, field=None):
		"""
		Raise a 422 with the give code, message and field (optional).
		"""
		data =	{
					u'code': code,
					u'message': message,
				}
		if field:
			data['field'] = field
		raise_json_error(self.request,
						 hexc.HTTPUnprocessableEntity,
						 data,
						 None)

	def _get_value(self, value_type, value, field):
		"""
		Get the value for the given type.
		"""
		if value_type == bool:
			result = value
			if isinstance( value, six.string_types ):
				result = is_true( value )
				if not result and is_false( value ):
					result = False
				elif not result:
					result = None
			if not isinstance( result, bool ):
				self._raise_error('InvalidType',
							  	  _('Value is invalid.'),
							  	  field=field)
		elif value_type == float:
			if not value:
				# Empty/None is acceptable.
				return None
			try:
				result = float(value)
				if result < 0:
					raise TypeError()
			except (TypeError, ValueError):
				self._raise_error('InvalidType',
							  	  _('Value is invalid.'),
							  	  field=field)
		else:
			raise TypeError()
		return result

	def update_policy(self, courses, ntiid, key, value):
		if key in SUPPORTED_DATE_KEYS:
			if value and not isinstance(value, datetime):
				value = IDateTime(value)
			for course in courses or ():
				dates = IQAssessmentDateContext(course)
				dates.set(ntiid, key, value)
				event_notify(QAssessmentDateContextModified(dates, ntiid, key))
			return

		part = None
		if key == 'auto_grade':
			# If auto_grade set to 'false', set 'disable' to true in auto_grade section.
			value = self._get_value(bool, value, key)
			part = 'auto_grade'
			value = not value
			key = 'disable'
		elif key == 'total_points':
			value = self._get_value(float, value, key)
			part = 'auto_grade'

		for course in courses or ():
			policy = self._get_or_create_policy_part(course, ntiid, part)
			policy[key] = value
			event_notify(QAssessmentPoliciesModified(course, ntiid, key, value))

	def updateContentObject(self, contentObject, externalValue, set_id=False,
							notify=True, pre_hook=None):
		# find all courses if context is not provided
		context = get_course_from_request(self.request)
		if context is None:
			courses = get_courses_from_assesment(contentObject)
		else:
			courses = (context,)

		self.preflight(contentObject, externalValue, courses)

		if context is not None:
			# Remove policy keys to avoid updating
			# fields in the actual assessment object
			backupData = copy.deepcopy(externalValue)
			for key in self.policy_keys:
				externalValue.pop(key, None)
		else:
			backupData = externalValue

		if externalValue:
			copied = copy.deepcopy(externalValue)
			result = UGDPutView.updateContentObject(self,
													notify=False,
													set_id=set_id,
													pre_hook=pre_hook,
													externalValue=externalValue,
													contentObject=contentObject)

			if notify:
				notifyModified(contentObject, copied)
		else:
			result = contentObject

		# update course policy
		ntiid = contentObject.ntiid
		for key in self.policy_keys:
			if key in backupData:
				self.update_policy(courses, ntiid, key, backupData[key])

		# Validate once we have policy updated.
		self.validate(result, externalValue, courses)
		return result

class StructuralValidationMixin(object):
	"""
	A mixin to validate the structural state of an IQEditableEvaluation object.
	"""

	@Lazy
	def course(self):
		# XXX: Evaluation has lineage access to its course.
		result = find_interface(self.context, ICourseInstance, strict=True)
		return result

	def _check_part_structure(self, context, externalValue):
		"""
		Determines whether this question part has structural changes.
		"""
		result = False
		ext_part_ntiid = externalValue.get( 'NTIID',
							externalValue.get( 'ntiid', '' ))
		obj_ntiid = getattr( context, 'ntiid', '' )
		if ext_part_ntiid and obj_ntiid and obj_ntiid != ext_part_ntiid:
			result = True
		else:
			analyzer = IQPartChangeAnalyzer(context, None)
			if analyzer is not None:
				# XXX: Is this what we want?
				result = not analyzer.allow(externalValue, check_solutions=False)
		return result

	def _check_question_structure(self, context, externalValue):
		"""
		Determines whether this question has structural changes.
		"""
		result = False
		ext_question_ntiid = externalValue.get( 'NTIID',
								externalValue.get( 'ntiid', '' ))
		parts = context.parts or ()
		ext_parts = externalValue.get( 'parts' )
		if	 	ext_question_ntiid \
			and context.ntiid != ext_question_ntiid:
			result = True
		elif 	ext_parts is not None \
			and len( parts ) != len( ext_parts ):
			result = True
		elif ext_parts is not None:
			for idx, part in enumerate( context.parts or () ):
				ext_part = externalValue.get( 'parts' )[idx]
				result = self._check_part_structure( part, ext_part )
				if result:
					break
		return result

	def _check_question_set_structure(self, context, externalValue):
		"""
		Determines whether this question set has structural changes.
		"""
		result = False
		questions = context.questions or ()
		ext_questions = externalValue.get( 'questions' )
		ext_question_set_ntiid = externalValue.get( 'NTIID',
									externalValue.get( 'ntiid', '' ))
		if 		ext_questions is not None \
			and len( questions ) != len( ext_questions ):
			result = True
		elif 	ext_question_set_ntiid \
			and context.ntiid != ext_question_set_ntiid:
			result = True
		elif ext_questions is not None:
			for idx, question in enumerate( questions ):
				ext_question = ext_questions[idx]
				result = self._check_question_structure( question, ext_question )
				if result:
					break
		return result

	def _check_assignment_part_structure(self, context, externalValue):
		"""
		Determines whether this assignment part has structural changes.
		"""
		result = False
		ext_part_ntiid = externalValue.get( 'NTIID',
								externalValue.get( 'ntiid', '' ))
		if	 	ext_part_ntiid \
			and context.ntiid != ext_part_ntiid:
			result = True
		else:
			ext_set = externalValue.get( 'question_set' )
			if ext_set is not None:
				result = self._check_question_set_structure( context.question_set,
															 ext_set )
		return result

	def _check_assignment_structure(self, context, externalValue):
		"""
		Determines whether this assignment has structural changes.
		"""
		result = False
		ext_parts = externalValue.get( 'parts' )
		if ext_parts is not None:
			result = len( context.parts or () ) != len( ext_parts )
			if not result:
				for idx, part in enumerate( context.parts or () ):
					ext_part = externalValue.get( 'parts' )[idx]
					result = self._check_assignment_part_structure( part, ext_part )
					if result:
						break
		return result

	def _check_structural_change(self, context, externalValue):
		"""
		For the given evaluation and input, check if 'structural' changes
		are being made.
		"""
		# We do not allow part level modifications.
		result = False
		if IQAssignment.providedBy( context ):
			result = self._check_assignment_structure( context, externalValue )
		elif IQuestionSet.providedBy( context ):
			result = self._check_question_set_structure( context, externalValue )
		elif IQuestion.providedBy( context ):
			result = self._check_question_structure( context, externalValue )
		return result

	def _validate_structural_edits(self, context=None):
		"""
		Validate we are allowed to change the given context's
		structural state.
		"""
		context = context if context is not None else self.context
		# Validate for all possible courses.
		courses = get_courses( self.course )
		for course in courses:
			validate_structural_edits( context, course )

	def _pre_flight_validation(self, context, externalValue=None, structural_change=False):
		"""
		Validate whether the incoming changes are 'structural' changes that
		require submission validation or a version bump of containing assignments.
		"""
		# Only validate editable items.
		if not IQEditableEvaluation.providedBy(context):
			return

		if not structural_change:
			structural_change = self._check_structural_change( context,
															   externalValue )
		if structural_change:
			# We have changes, validate and bump version.
			self._validate_structural_edits( context )
			assignments = get_assignments_for_evaluation_object( context )
			for assignment in assignments:
				assignment.update_version()
