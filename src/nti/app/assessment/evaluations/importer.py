#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

# from zope import interface
# 
# from nti.app.assessment.evaluations.utils import export_evaluation_content
# 
# from nti.app.assessment.interfaces import ICourseEvaluations
# 
# from nti.app.assessment.utils import copy_evaluation
# 
# from nti.app.products.courseware.resources.utils import get_course_filer
# 
# from nti.assessment import EVALUATION_INTERFACES
# 
# from nti.common.proxy import removeAllProxies
# 
# from nti.contenttypes.courses.interfaces import ICourseInstance
# from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
# from nti.contenttypes.courses.interfaces import ICourseSectionImporter
# 
# from nti.contenttypes.courses.importer import BaseSectionImporter
# 
# from nti.contenttypes.courses.utils import get_course_subinstances
# 
# from nti.externalization.externalization import to_external_object
# 
# from nti.externalization.interfaces import StandardExternalFields
# 
# ITEMS = StandardExternalFields.ITEMS
# 
# @interface.implementer(ICourseSectionImporter)
# class EvaluationsImporter(BaseSectionImporter):
# 
# 	def process(self, context, filer):
# 		result = self.externalize(context, filer)
# 		source = self.dump(result)
# 		filer.save("evaluation_index.json", source,
# 				   contentType="application/json", overwrite=True)
# 		return result
