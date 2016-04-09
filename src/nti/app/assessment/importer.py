#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.component.hooks import site as current_site

from nti.app.assessment._question_map import populate_question_map_json
from nti.app.assessment._question_map import remove_assessment_items_from_oldcontent

from nti.app.assessment.common import get_resource_site_name

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_parent_course

from nti.site.hostpolicy import get_host_site

@interface.implementer(ICourseSectionImporter)
class AssessmentsImporter(BaseSectionImporter):

	def process(self, context, filer):
		course = ICourseInstance(context)
		course = get_parent_course(course)
		source = filer.get("assessment_index.json")
		if source is not None:
			source = self.load(source)
			for package in get_course_packages(course):
				site = get_resource_site_name(package)
				site = get_host_site(site)
				with current_site(site):
					remove_assessment_items_from_oldcontent(package, force=True)
					populate_question_map_json(source, package)
