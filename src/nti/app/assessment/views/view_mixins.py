#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import copy

from zope import component

from zope.interface.common.idatetime import IDateTime

from zope.intid import IIntIds

from nti.appserver.ugd_edit_views import UGDPutView

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import SUPPORTED_DATE_KEYS

from nti.contenttypes.courses.utils import get_course_packages

from nti.traversal.traversal import find_interface

from nti.zope_catalog.catalog import ResultSet

from .._utils import get_course_from_request

from ..index import IX_COURSE
from ..index import IX_ASSESSMENT_ID

from ..interfaces import IUsersCourseInquiryItem
from ..interfaces import IUsersCourseAssignmentHistoryItem

from .. import get_assesment_catalog

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

	def get_submissions(self, assesment, courses=()):
		if not courses:
			return ()
		else:
			catalog = get_assesment_catalog()
			intids = component.getUtility(IIntIds)
			uids = {intids.getId(x) for x in courses}
			query = { IX_COURSE: {'any_of':uids},
			 		  IX_ASSESSMENT_ID: {'any_of':(assesment.ntiid,)} }

			result = []
			uids = catalog.apply(query) or ()
			for item in ResultSet(uids, intids, True):
				if		IUsersCourseInquiryItem.providedBy(item) \
					or	IUsersCourseAssignmentHistoryItem.providedBy(item):
					result.append(item)
			return result

	def preflight(self, contentObject, externalValue, courses=()):
		pass

	def validate(self, contentObject, externalValue, courses=()):
		pass

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
			# remove policy keys to avoid updating
			# fields in the actual assessment object
			backupData = copy.copy(externalValue)
			for key in SUPPORTED_DATE_KEYS:
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

		# update course policies
		ntiid = contentObject.ntiid
		for key in SUPPORTED_DATE_KEYS:
			if key not in backupData:
				continue
			value = IDateTime(backupData[key])
			for course in courses:
				dates = IQAssessmentDateContext(course)
				dates.set(ntiid, key, value)
		return result
