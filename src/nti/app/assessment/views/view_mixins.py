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

from nti.appserver.ugd_edit_views import UGDPutView

from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import SUPPORTED_DATE_KEYS

from nti.contenttypes.courses.utils import get_course_packages

from nti.traversal.traversal import find_interface

from .._utils import get_course_from_request

def get_courses_from_assesment(assesment):
	package = find_interface(assesment, IContentPackage, strict=False)
	if package is None:
		return ()

	# Nothing. OK, maybe we're an instructor?
	catalog = component.queryUtility(ICourseCatalog)
	if catalog is None:
		return ()

	result = []
	for entry in catalog.iterCatalogEntries():
		packages = get_course_packages(entry)
		if package in packages:
			result.append(ICourseInstance(entry))
	return result

class AssessmentPutView(UGDPutView):

	def readInput(self, value=None):
		# TODO Validations?
		result = UGDPutView.readInput(self, value=value)
		result.pop('ntiid', None)
		result.pop('NTIID', None)
		return result

	def updateContentObject(self, contentObject, externalValue, set_id=False,
							notify=True, pre_hook=None):
		context = get_course_from_request(self.request)
		if context is not None:
			# remove policy keys to avoid updating
			# fields in the actual assessment object
			backupData = copy.copy(externalValue)
			for key in SUPPORTED_DATE_KEYS:
				externalValue.pop(key, None)
		else:
			backupData = externalValue

		# update
		result = UGDPutView.updateContentObject(self,
												notify=notify,
												set_id=set_id,
												pre_hook=pre_hook,
												externalValue=backupData,
												contentObject=contentObject)

		# find all courses if context is not provided
		if context is None:
			courses = get_courses_from_assesment(contentObject)
		else:
			courses = (context,)

		# update course policies
		ntiid = contentObject.ntiid
		for key in SUPPORTED_DATE_KEYS:
			if key not in backupData:
				continue
			for course in courses:
				dates = IQAssessmentDateContext(course)
				dates.set(ntiid, key, backupData[key])
		return result
