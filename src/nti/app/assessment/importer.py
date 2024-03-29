#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import os

from zope import interface

from zope.component.hooks import site as current_site

from nti.app.assessment.synchronize import populate_question_map_json
from nti.app.assessment.synchronize import remove_assessment_items_from_oldcontent

from nti.cabinet.filer import transfer_to_native_file

from nti.contentlibrary.interfaces import IFilesystemBucket
from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_parent_course

from nti.site.interfaces import IHostPolicyFolder

logger = __import__('logging').getLogger(__name__)


@interface.implementer(ICourseSectionImporter)
class AssessmentsImporter(BaseSectionImporter):

    ASSESSMENT_INDEX = "assessment_index.json"

    def remove_assessments(self, package):
        remove_assessment_items_from_oldcontent(package, True)

    def process(self, context, filer, writeout=False):
        course = ICourseInstance(context)
        course = get_parent_course(course)
        source = filer.get(self.ASSESSMENT_INDEX)
        if source is not None:
            result = set()
            source = self.load(source)
            for package in get_course_packages(course):
                if IEditableContentPackage.providedBy(package):
                    continue
                site = IHostPolicyFolder(package)
                with current_site(site):
                    self.remove_assessments(package)
                    result.update(populate_question_map_json(source, package))
                # save source
                if writeout and IFilesystemBucket.providedBy(package.root):
                    source = filer.get(self.ASSESSMENT_INDEX)  # reload
                    self.makedirs(package.root.absolute_path)  # create
                    new_path = os.path.join(package.root.absolute_path,
                                            self.ASSESSMENT_INDEX)
                    transfer_to_native_file(source, new_path)
            return result
        return ()
