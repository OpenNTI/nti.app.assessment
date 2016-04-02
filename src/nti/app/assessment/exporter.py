#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from StringIO import StringIO

import simplejson

from zope import interface

from nti.app.assessment.common import get_unit_assessments

from nti.common.file import safe_filename

from nti.common.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.utils import get_parent_course

from nti.externalization.externalization import toExternalObject

from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

@interface.implementer(ICourseSectionExporter)
class AssessmentsExporter(object):

	def mapped(self, package, items):

		def _recur(unit, items):
			# all units have a map
			items[unit.ntiid] = dict()
			# collect evaluations
			evaluations = dict()
			for evaluation in get_unit_assessments(unit):
				evaluation = removeAllProxies(evaluation)
				ext_obj = toExternalObject(evaluation, name="exporter")
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
				# add legacy
				items[unit.ntiid][NTIID] = unit.ntiid
				items[unit.ntiid]['filename'] = safe_filename(unit.ntiid) + '.html'
		_recur(package, items)
		if package.ntiid in items:
			items[package.ntiid]['filename'] = 'index.html'

	def externalize(self, context):
		result = {}
		course = ICourseInstance(context)
		course = get_parent_course(course)
		items = result[ITEMS] = dict()
		for package in get_course_packages(course):
			self.mapped(package, items)
		return result

	def export(self, context, filer):
		result = self.externalize(context)
		source = StringIO()
		simplejson.dump(result, source, indent=4, sort_keys=True)
		source.seek(0)
		# save in filer
		filer.save("assessment_index.json", source,
				   contentType="application/json", overwrite=True)
