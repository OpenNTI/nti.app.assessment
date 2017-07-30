#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import Mapping

from zope import interface

from nti.app.assessment.evaluations.utils import export_evaluation_content

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.assessment.utils import copy_evaluation

from nti.assessment import EVALUATION_INTERFACES

from nti.assessment.common import is_randomized_question_set
from nti.assessment.common import is_randomized_parts_container

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation

from nti.externalization.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.exporter import hash_ntiid
from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

class EvaluationsExporterMixin(object):

    def change_evaluation_ntiid(self, ext_obj, salt=None):
        if isinstance(ext_obj, Mapping):
            # when not backing up make sure we take a hash of the current NTIID and
            # use it as the specific part for a new NTIID to make sure there are
            # fewer collisions when importing back
            for name in (NTIID, NTIID.lower()):
                ntiid = ext_obj.get(name)
                if ntiid:
                    ext_obj[name] = hash_ntiid(ntiid, salt)
            for value in ext_obj.values():
                self.change_evaluation_ntiid(value, salt)
        elif isinstance(ext_obj, (list, tuple, set)):
            for value in ext_obj:
                self.change_evaluation_ntiid(value, salt)

    def evaluations(self, context):
        evaluations = IQEvaluations(context)
        for item in evaluations.values():
            if IQEditableEvaluation.providedBy(item):
                yield item

    def do_evaluations_export(self, context, target_filer=None, backup=True, salt=None):
        order = {i: x for i, x in enumerate(EVALUATION_INTERFACES)}.items()

        def _get_key(item):
            for i, iface in order:
                if iface.providedBy(item):
                    return i
            return 0

        def _ext(item):
            evaluation = removeAllProxies(item)
            if target_filer is not None:
                # Copy evaluation b/c changes in content may be done
                # during the export
                evaluation = copy_evaluation(evaluation)
                export_evaluation_content(evaluation, target_filer)
            ext_obj = to_external_object(evaluation,
                                         name="exporter",
                                         decorate=False)

            if IQuestionSet.providedBy(evaluation):
                ext_obj['Randomized'] = is_randomized_question_set(evaluation)
                ext_obj['RandomizedPartsType'] = is_randomized_parts_container(evaluation)

            if IQAssignment.providedBy(evaluation):
                # This is an assignment, so we need to drill down to the actual
                # question set in order to set randomized attributes.
                for index, part in enumerate(evaluation.parts or ()):
                    qs = part.question_set
                    ext_part_obj = ext_obj['parts'][index]
                    if qs is not None:
                        qs_ext = ext_part_obj['question_set']
                        qs_ext['Randomized'] = is_randomized_question_set(qs)
                        qs_ext['RandomizedPartsType'] = is_randomized_parts_container(qs)

            if not backup:
                self.change_evaluation_ntiid(ext_obj, salt)
            return ext_obj

        ordered = sorted(self.evaluations(context), key=_get_key)
        return map(_ext, ordered)

    def export_evaluations(self, context, filer=None, backup=True, salt=None):
        result = LocatedExternalDict()
        items = self.do_evaluations_export(context, filer, backup, salt)
        if items:  # check
            result[ITEMS] = items
            result[TOTAL] = result[ITEM_COUNT] = len(items)
        return result


@interface.implementer(ICourseSectionExporter)
class EvaluationsExporter(EvaluationsExporterMixin, BaseSectionExporter):

    def externalize(self, context, filer=None, backup=True, salt=None):
        course = ICourseInstance(context)
        return EvaluationsExporterMixin.export_evaluations(self, course, filer, backup, salt)

    def export(self, context, filer, backup=True, salt=None):
        course = ICourseInstance(context)
        for course in get_course_hierarchy(course):
            bucket = self.course_bucket(course)
            result = self.externalize(course, filer, backup, salt)
            if result:  # check
                source = self.dump(result)
                filer.save("evaluation_index.json", source, bucket=bucket,
                           contentType="application/json", overwrite=True)
        return result
