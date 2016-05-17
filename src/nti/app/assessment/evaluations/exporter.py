#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.assessment.utils import copy_evaluation

from nti.assessment import EVALUATION_INTERFACES

from nti.common.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS

@interface.implementer(ICourseSectionExporter)
class EvaluationsExporter(BaseSectionExporter):

	def _output(self, course, store, filer=None):
		entry = ICourseCatalogEntry(course)
		evaluations = ICourseEvaluations(course)

		order = {i:x for i, x in enumerate(EVALUATION_INTERFACES)}.items()
		def _get_key(item):
			for i, iface in order:
				if iface.providedBy(item):
					return i
			return 0

		def _ext(item):
			evaluation = copy_evaluation(removeAllProxies(item))
			ext_obj = to_external_object(evaluation, name="exporter", decorate=False)
			return ext_obj

		key = entry.ProviderUniqueID
		items = sorted(evaluations.values(), key=_get_key)
		store[key] = map(_ext, items)

	def externalize(self, context, filer=None):
		result = dict()
		course = ICourseInstance(context)
		items = result[ITEMS] = dict()
		courses = (course,) + tuple(get_course_subinstances(course))
		for course in courses:
			self._output(course, items, filer=filer)
		return result

	def export(self, context, filer):
		result = self.externalize(context)
		source = self.dump(result)
		filer.save("evaluation_index.json", source,
				   contentType="application/json", overwrite=True)
		return result
