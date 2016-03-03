#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import copy
from datetime import datetime

from pyramid import httpexceptions as hexc

from zope import component

from zope.event import notify as event_notify

from zope.interface.common.idatetime import IDateTime

from zope.intid.interfaces import IIntIds

from nti.app.assessment import get_assesment_catalog

from nti.app.assessment.common import get_available_for_submission_ending
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import IX_ASSESSMENT_ID

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views import MessageFactory as _

from nti.app.externalization.error import raise_json_error

from nti.appserver.ugd_edit_views import UGDPutView

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import QAssessmentDateContextModified

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.interfaces import SUPPORTED_DATE_KEYS

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import StandardExternalFields

from nti.links.links import Link

from nti.site.interfaces import IHostPolicyFolder

from nti.traversal.traversal import find_interface

from nti.zope_catalog.catalog import ResultSet

CLASS = StandardExternalFields.CLASS
LINKS = StandardExternalFields.LINKS
MIME_TYPE = StandardExternalFields.MIMETYPE

def canonicalize_question_set(self, obj, registry=component):
	obj.questions = [registry.getUtility(IQuestion, name=x.ntiid)
					 for x
					 in obj.questions]

def canonicalize_assignment(obj, registry=component):
	for part in obj.parts:
		ntiid = part.question_set.ntiid
		part.question_set = registry.getUtility(IQuestionSet, name=ntiid)
		canonicalize_question_set(part.question_set, registry)

def get_courses_from_assesment(assesment):
	package = find_interface(assesment, IContentPackage, strict=False)
	if package is None:
		return ()

	catalog = component.queryUtility(ICourseCatalog)
	if catalog is None:
		return ()

	result = set()
	for entry in catalog.iterCatalogEntries():
		packages = get_course_packages(entry)
		if package in packages:
			result.add(ICourseInstance(entry))
	return result

class AssessmentPutView(UGDPutView):

	def readInput(self, value=None):
		result = UGDPutView.readInput(self, value=value)
		result.pop('ntiid', None)
		result.pop('NTIID', None)
		return result

	def get_site_name(self, course):
		folder = find_interface(course, IHostPolicyFolder, strict=False)
		return folder.__name__ if folder is not None else u''

	def get_ntiids(self, courses):
		ntiids = {getattr(ICourseCatalogEntry(x, None), 'ntiid', None) for x in courses}
		ntiids.discard(None)
		return ntiids

	def has_submissions(self, assessment, courses=()):
		if not courses:
			return False
		else:
			catalog = get_assesment_catalog()
			ntiids = self.get_ntiids(courses)
			intids = component.getUtility(IIntIds)
			sites = {self.get_site_name(x) for x in courses}
			query = {
			 	IX_SITE: {'any_of':sites},
				IX_COURSE: {'any_of':ntiids},
			 	IX_ASSESSMENT_ID: {'any_of':(assessment.ntiid,)}
			 }

			uids = catalog.apply(query) or ()
			for item in ResultSet(uids, intids, True):
				if		IUsersCourseInquiryItem.providedBy(item) \
					or	IUsersCourseAssignmentHistoryItem.providedBy(item):
					return True
			return False

	def has_savepoints(self, assessment, courses=()):
		assessment_id = assessment.ntiid
		for course in courses:
			savepoints = IUsersCourseAssignmentSavepoints( course, None )
			if savepoints:
				for history in savepoints.values():
					if history.get( assessment_id ):
						return True
		return False

	def _raise_conflict_error(self, code, message):
		links =( Link(self.request.path, rel='confirm',
					  params={'force':True}, method='PUT'),)
		raise_json_error(self.request,
						 hexc.HTTPConflict,
						 {
						 	CLASS: 'DestructiveChallenge',
							u'message': message,
							u'code': code,
							LINKS: to_external_object( links ),
							MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
						 },
						 None)

	def _is_date_in_range(self, start_date, end_date, now):
		"""
		Returns if we are currently within a possibly open-ended date range.
		"""
		result = 	(not start_date or start_date < now) \
				and (not end_date or now < end_date)
		return result

	def validate_dates(self, contentObject, externalValue, courses=()):
		"""
		Validates that the assessment does not change availability states. If
		so, we throw a 409 with an available `confirm` link for user overrides.
		"""
		_marker = object()
		new_start_date = externalValue.get( 'available_for_submission_beginning', _marker )
		new_end_date = externalValue.get( 'available_for_submission_ending', _marker )
		if 		new_start_date is not _marker \
			or  new_end_date is not _marker:

			now = datetime.utcnow()
			if new_start_date and new_start_date is not _marker:
				new_start_date = IDateTime( new_start_date )
			if new_end_date and new_end_date is not _marker:
				new_end_date = IDateTime( new_end_date )

			for course in courses:
				old_start_date = get_available_for_submission_beginning( contentObject, course )
				old_end_date = get_available_for_submission_ending( contentObject, course )
				# Use old dates if the dates are not being edited.
				start_date_to_check = old_start_date if new_start_date is _marker else new_start_date
				end_date_to_check = old_end_date if new_end_date is _marker else new_end_date

				old_available = self._is_date_in_range( old_start_date, old_end_date, now )
				new_available = self._is_date_in_range( start_date_to_check, end_date_to_check, now )

				# Note: we allow state to move from closed in past to
				# closed, but will reopen in the future unchecked (edge case).
				if old_available and not new_available:
					self._raise_conflict_error( 'AvailableToUnavailable',
												_( 'Editing object will make it unavailable. Please confirm.' ))
				elif not old_available and new_available:
					self._raise_conflict_error( 'UnAvailableToAvailable',
												_( 'Editing object will make it available. Please confirm.' ))

	def preflight(self, contentObject, externalValue, courses=()):
		# We could validate edits based on the unused submission/savepoint
		# code above, based on the input keys being changed.
		if not self.request.params.get( 'force', False ):
			self.validate_dates(contentObject, externalValue, courses)

	def validate(self, contentObject, externalValue, courses=()):
		pass

	@property
	def policy_keys(self):
		return SUPPORTED_DATE_KEYS

	def update_policy(self, courses, ntiid, key, value):
		if key in SUPPORTED_DATE_KEYS:
			if value and not isinstance( value, datetime ):
				value = IDateTime( value )
			for course in courses:
				dates = IQAssessmentDateContext(course)
				dates.set(ntiid, key, value)
				event_notify(QAssessmentDateContextModified(dates, ntiid, key))

	def updateContentObject(self, contentObject, externalValue, set_id=False,
							notify=True, pre_hook=None):
		# find all courses if context is not provided
		context = get_course_from_request(self.request)
		if context is None:
			# TODO: Use course catalog index?
			courses = get_courses_from_assesment(contentObject)
		else:
			courses = (context,)

		self.preflight(contentObject, externalValue, courses)

		if context is not None:
			# Remove policy keys to avoid updating
			# fields in the actual assessment object
			backupData = copy.copy(externalValue)
			for key in self.policy_keys:
				externalValue.pop(key, None)
		else:
			backupData = externalValue

		if externalValue:
			result = UGDPutView.updateContentObject(self,
													notify=notify,
													set_id=set_id,
													pre_hook=pre_hook,
													externalValue=externalValue,
													contentObject=contentObject)

			self.validate(result, externalValue, courses)
		else:
			result = contentObject

		# update course policy
		ntiid = contentObject.ntiid
		for key in self.policy_keys:
			if key in backupData:
				self.update_policy(courses, ntiid, key, backupData[key])
		return result
