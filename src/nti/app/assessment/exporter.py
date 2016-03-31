#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import re
from StringIO import StringIO
from collections import Mapping

import simplejson

from zope import interface

from nti.app.assessment.common import get_unit_assessments

from nti.common.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.utils import get_parent_course

from nti.externalization.externalization import toExternalObject

from nti.externalization.interfaces import StandardExternalFields

from nti.mimetype import decorateMimeType

from nti.ntiids.ntiids import TYPE_OID
from nti.ntiids.ntiids import is_ntiid_of_type

OID = StandardExternalFields.OID
ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
MIMETYPE = StandardExternalFields.MIMETYPE
CONTAINER_ID = StandardExternalFields.CONTAINER_ID

def safe_filename(s):
	return re.sub(r'[/<>:"\\|?*]+', '_', s) if s else s

@interface.implementer(ICourseSectionExporter)
class AssessmentsExporter(object):

	def decorate_callback(self, obj, result):
		if isinstance(result, Mapping) and MIMETYPE not in result:
			decorateMimeType(obj, result)

	def _remover(self, result):
		if isinstance(result, Mapping):
			for name, value in list(result.items()):
				if name in (OID, CONTAINER_ID, 'containerId'):
					result.pop(name, None)
				elif name == NTIID and is_ntiid_of_type(value, TYPE_OID):
					result.pop(name, None)
				else:
					self._remover(value)
		elif isinstance(result, (list, tuple)):
			for value in result:
				self._remover(value)
		return result

	def mapped(self, package, items):
		def _recur(unit, items):
			# all units have a map
			items[unit.ntiid] = dict()
			# collect evaluations
			evaluations = dict()
			for evaluation in get_unit_assessments(unit):
				evaluation = removeAllProxies(evaluation)
				ext_obj = toExternalObject(evaluation, 
							   			   decorate=False,
										   decorate_callback=self.decorate_callback)
				ext_obj = self._remover(ext_obj)
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

	def export(self, context, filer):
		result = {}
		course = ICourseInstance(context)
		course = get_parent_course(course)
		items = result[ITEMS] = dict()
		for package in get_course_packages(course):
			self.mapped(package, items)
		# export to json
		source = StringIO()
		simplejson.dump(result, source, indent=4, sort_keys=True)
		source.seek(0)
		# save in filer
		filer.save("assessment_index.json", source, 
				   contentType="application/json", overwrite=True)
