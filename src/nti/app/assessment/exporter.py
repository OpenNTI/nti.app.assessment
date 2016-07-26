#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.common import get_unit_assessments

from nti.assessment.interfaces import IQEditableEvaluation

from nti.common.file import safe_filename

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.utils import get_parent_course

from nti.externalization.externalization import to_external_object

from nti.externalization.proxy import removeAllProxies

from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

@interface.implementer(ICourseSectionExporter)
class AssessmentsExporter(BaseSectionExporter):

	def mapped(self, package, items):

		def _recur(unit, items):
			# all units have a map
			items[unit.ntiid] = dict()
			# collect evaluations
			evaluations = dict()
			for evaluation in get_unit_assessments(unit):
				evaluation = removeAllProxies(evaluation)
				if IQEditableEvaluation.providedBy(evaluation):
					continue
				ext_obj = to_external_object(evaluation, name="exporter", decorate=False)
				evaluations[evaluation.ntiid] = ext_obj
			items[unit.ntiid]['AssessmentItems'] = evaluations
			# create new items for children
			child_items = items[unit.ntiid][ITEMS] = dict()
			for child in unit.children:
				_recur(child, child_items)
			# remove empty
			if not evaluations and not child_items:
				items.pop(unit.ntiid, None)
			else:
				if not evaluations:
					items[unit.ntiid].pop('AssessmentItems', None)
				# XXX: add legacy required for importimg
				items[unit.ntiid][NTIID] = unit.ntiid
				items[unit.ntiid]['filename'] = safe_filename(unit.ntiid) + '.html'

		_recur(package, items)
		if package.ntiid in items:
			# XXX: add legacy required for importimg
			items[package.ntiid]['filename'] = 'index.html'

	def externalize(self, context):
		result = dict()
		course = ICourseInstance(context)
		course = get_parent_course(course)
		items = result[ITEMS] = dict()
		for package in get_course_packages(course):
			self.mapped(package, items)
		return result

	def export(self, context, filer):
		result = self.externalize(context)
		source = self.dump(result)
		filer.save("assessment_index.json", source,
				   contentType="application/json", overwrite=True)
		return result
