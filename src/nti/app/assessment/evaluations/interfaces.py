#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.contenttypes.courses.interfaces import ICourseSectionExporter
from nti.contenttypes.courses.interfaces import ICourseSectionImporter


class ICourseEvaluationsSectionExporter(ICourseSectionExporter):
    pass


class ICourseEvaluationsSectionImporter(ICourseSectionImporter):
    pass
