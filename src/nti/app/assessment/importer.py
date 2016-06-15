#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os

from zope import interface

from zope.component.hooks import site as current_site

from nti.app.assessment._question_map import populate_question_map_json
from nti.app.assessment._question_map import remove_assessment_items_from_oldcontent

from nti.app.assessment.common import get_resource_site_name

from nti.cabinet.filer import transfer_to_native_file

from nti.contentlibrary.interfaces import IFilesystemBucket

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_parent_course

from nti.site.hostpolicy import get_host_site

@interface.implementer(ICourseSectionImporter)
class AssessmentsImporter(BaseSectionImporter):

	ASSESSMENT_INDEX = "assessment_index.json"
	
	def process(self, context, filer, writeout=True):
		course = ICourseInstance(context)
		course = get_parent_course(course)
		source = filer.get(self.ASSESSMENT_INDEX)
		if source is not None:
			source = self.load(source)
			for package in get_course_packages(course):
				site = get_resource_site_name(package)
				site = get_host_site(site)
				with current_site(site):
					remove_assessment_items_from_oldcontent(package, force=True)
					return populate_question_map_json(source, package)
				# save source
				if writeout and IFilesystemBucket.providedBy(package.root):
					source = filer.get(self.ASSESSMENT_INDEX) # reload
					self.makedirs(package.root.absolute_path) # create
					new_path = os.path.join(package.root.absolute_path, self.ASSESSMENT_INDEX)
					transfer_to_native_file(source, new_path)
		return ()
