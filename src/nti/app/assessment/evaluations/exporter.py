#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.evaluations.utils import export_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.products.courseware.resources.utils import get_course_filer

from nti.assessment import EVALUATION_INTERFACES

from nti.common.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS

@interface.implementer(ICourseSectionExporter)
class EvaluationsExporter(BaseSectionExporter):

	def _output(self, course, target_filer=None):
		evaluations = ICourseEvaluations(course)
		source_filer = get_course_filer(course)
		
		order = {i:x for i, x in enumerate(EVALUATION_INTERFACES)}.items()
		def _get_key(item):
			for i, iface in order:
				if iface.providedBy(item):
					return i
			return 0

		def _ext(item):
			evaluation = removeAllProxies(item)
			if target_filer is not None:
				export_evaluation_content(evaluation, source_filer, target_filer)
			ext_obj = to_external_object(evaluation, name="exporter", decorate=False)
			return ext_obj

		ordered = sorted(evaluations.values(), key=_get_key)
		return map(_ext, ordered)

	def externalize(self, context, filer=None):
		result = dict()
		course = ICourseInstance(context)
		result[ITEMS] = self._output(course, target_filer=filer)
		return result

	def export(self, context, filer):
		course = ICourseInstance(context)
		courses = ( course, ) + tuple(get_course_subinstances(course))
		for course in courses:
			bucket = self.course_bucket(course)
			result = self.externalize(course, filer)
			source = self.dump(result)
			filer.save("evaluation_index.json", source, bucket=bucket,
				   		contentType="application/json", overwrite=True)
		return result
