#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from functools import partial

from zope import component

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata

from nti.assessment.interfaces import IQEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance, ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalAdministrativeRoleCatalog

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ISystemUserPrincipal

from nti.metadata.predicates import BasePrincipalObjects

from nti.site.hostpolicy import run_job_in_all_host_sites

from nti.zodb import isBroken

def _get_courses_from_enrollments(user, provided=IPrincipalEnrollments,
								  method='iter_enrollments'):
	for enrollments in component.subscribers((user,), provided):
		for enrollment in getattr(enrollments, method)():
			course = ICourseInstance(enrollment, None)
			if course is not None and not isBroken(course):
				yield course

def _add_to_result(result, item):
	if not isBroken(item):
		result.append(item)

@component.adapter(IUser)
class _AssignmentHistoryPrincipalObjects(BasePrincipalObjects):

	def _feedbackitem_collector(self, feedback, creator):
		for x in feedback.Items:
			if x.creator == creator:
				yield x

	def _history_collector(self, result):
		user = self.user
		for course in _get_courses_from_enrollments(user):
			items = component.queryMultiAdapter((course, user),
												IUsersCourseAssignmentHistory)
			if not items:
				continue
			_add_to_result(result, items)
			for item in items.values():
				_add_to_result(result, item)
				_add_to_result(result, item.Submission)
				_add_to_result(result, item.pendingAssessment)

				feedback = item.Feedback
				if feedback is not None:
					for item in self._feedbackitem_collector(feedback, user):
						_add_to_result(result, item)

			# collect metadata
			items = component.queryMultiAdapter((course, user),
												IUsersCourseAssignmentMetadata)
			if not items:
				continue
			_add_to_result(result, items)
			for item in items.values():
				_add_to_result(result, item)
		return result

	def _feedback_collector(self, result):
		user = self.user
		for course in _get_courses_from_enrollments(user,
													IPrincipalAdministrativeRoleCatalog,
													'iter_administrations'):
			enrollments = ICourseEnrollments(course)
			for record in enrollments.iter_enrollments():
				student = IUser(record.principal, None)
				if student is None:
					continue
				items = component.queryMultiAdapter((course, student),
													 IUsersCourseAssignmentHistory)
				if not items:
					continue
				for item in items:
					feedback = item.Feedback
					if feedback is not None:
						for item in self._feedbackitem_collector(feedback, user):
							_add_to_result(result, item)
		return result

	def _collector(self, result):
		self._history_collector(result)
		self._feedback_collector(result)

	def iter_objects(self):
		result = []
		run_job_in_all_host_sites(partial(self._collector, result))
		return result

@component.adapter(IUser)
class _InquiryPrincipalObjects(BasePrincipalObjects):

	def _item_collector(self, result):
		user = self.user
		for course in _get_courses_from_enrollments(user):
			items = component.queryMultiAdapter((course, user), IUsersCourseInquiry)
			if not items:
				continue
			_add_to_result(result, items)
			for item in items.values():
				_add_to_result(result, item)
				_add_to_result(result, item.Submission)
		return result

	def iter_objects(self):
		result = []
		run_job_in_all_host_sites(partial(self._item_collector, result))
		return result

@component.adapter(ISystemUserPrincipal)
class _EvaluationObjects(BasePrincipalObjects):

	def iter_items(self, result, seen):
		for ntiid, item in list(component.getUtilitiesFor(IQEvaluation)):
			if ntiid not in seen:
				seen.add(ntiid)
				result.append(item)

		catalog = component.getUtility(ICourseCatalog)
		for entry in catalog.iterCatalogEntries():
			if entry.ntiid not in seen:
				seen.add(entry.ntiid)
				course = ICourseInstance(entry)
				evaluations = ICourseEvaluations(course)
				for ntiid, e in list(evaluations.items()):
					if ntiid not in seen:
						seen.add(ntiid)
						result.extend(e)

	def iter_objects(self):
		result = []
		seen = set()
		run_job_in_all_host_sites(partial(self.iter_items, result, seen))
		return result
