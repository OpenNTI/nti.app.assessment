#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import hashlib
from collections import Mapping

from zope import interface

from nti.app.assessment.evaluations.utils import export_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.assessment.utils import copy_evaluation

from nti.app.products.courseware.resources.utils import get_course_filer

from nti.assessment import EVALUATION_INTERFACES

from nti.externalization.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import get_parts
from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import make_specific_safe

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

@interface.implementer(ICourseSectionExporter)
class EvaluationsExporter(BaseSectionExporter):

	def hexdigest(self, data):
		hasher = hashlib.sha256()
		hasher.update(data)
		return hasher.hexdigest()

	def _change_ntiid(self, ext_obj):
		if isinstance(ext_obj, Mapping):
			# when not backing up make sure we take a hash of the current NTIID and
			# use it as the specific part for a new NTIID to make sure there are
			# fewer collisions when importing back
			for name in (NTIID, NTIID.lower()):
				if name in ext_obj:
					ntiid = ext_obj[name]
					parts = get_parts(ntiid)
					digest = self.hexdigest(ntiid)
					specific = make_specific_safe("%s_%04d" % (digest, len(ntiid)))
					ntiid = make_ntiid(parts.date, 
									   parts.provider,
									   parts.nttype, 
									   specific=specific)
					ext_obj[name] = ntiid
			for value in ext_obj.values():
				self._change_ntiid(value)
		elif isinstance(ext_obj, (list, tuple, set)):
			for value in ext_obj:
				self._change_ntiid(value)

	def _output(self, course, target_filer=None, backup=True):
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
				# Copy evaluation b/c changes in content may be done during the export
				evaluation = copy_evaluation(evaluation)
				export_evaluation_content(evaluation, source_filer, target_filer)
			ext_obj = to_external_object(evaluation, name="exporter", decorate=False)
			if not backup:
				self._change_ntiid(ext_obj)
			return ext_obj

		ordered = sorted(evaluations.values(), key=_get_key)
		return map(_ext, ordered)

	def externalize(self, context, filer=None, backup=True):
		result = LocatedExternalDict()
		course = ICourseInstance(context)
		items = self._output(course, target_filer=filer, backup=backup)
		if items: # check
			result[ITEMS] = items
		return result

	def export(self, context, filer, backup=True):
		course = ICourseInstance(context)
		courses = get_course_hierarchy(course)
		for course in courses:
			bucket = self.course_bucket(course)
			result = self.externalize(course, filer, backup)
			if result:  # check
				source = self.dump(result)
				filer.save("evaluation_index.json", source, bucket=bucket,
					   		contentType="application/json", overwrite=True)
		return result
