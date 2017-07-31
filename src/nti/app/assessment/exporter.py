#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.common.evaluations import get_unit_assessments

from nti.assessment.interfaces import IQEditableEvaluation

from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.utils import get_parent_course

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.proxy import removeAllProxies

from nti.namedfile.file import safe_filename

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
                ext_obj = to_external_object(evaluation,
                                             name="exporter",
                                             decorate=False)
                evaluations[evaluation.ntiid] = ext_obj
            items[unit.ntiid]['AssessmentItems'] = evaluations
            # create new items for children
            child_items = items[unit.ntiid][ITEMS] = dict()
            for child in unit.children or ():
                _recur(child, child_items)
            # remove empty
            if not evaluations and not child_items:
                items.pop(unit.ntiid, None)
            else:
                if not evaluations:
                    items[unit.ntiid].pop('AssessmentItems', None)
                # XXX: add legacy required for importimg
                items[unit.ntiid][NTIID] = unit.ntiid
                filename = safe_filename(unit.ntiid) + '.html'
                items[unit.ntiid]['filename'] = filename

        _recur(package, items)
        if package.ntiid in items:
            # XXX: add legacy required for importimg
            items[package.ntiid]['filename'] = 'index.html'

    def externalize(self, context):
        result = LocatedExternalDict()
        course = ICourseInstance(context)
        course = get_parent_course(course)
        items = result[ITEMS] = dict()
        for package in get_course_packages(course):
            if not IEditableContentPackage.providedBy(package):
                self.mapped(package, items)
        return result

    def export(self, context, filer, unused_backup=True, unused_salt=None):
        result = self.externalize(context)
        source = self.dump(result)
        filer.save("assessment_index.json", source,
                   contentType="application/json", overwrite=True)
        return result
