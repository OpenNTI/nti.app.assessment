#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import Mapping

from zope import interface

from nti.app.assessment.evaluations.utils import export_evaluation_content
from nti.app.assessment.evaluations.utils import is_randomized_assignment
from nti.app.assessment.evaluations.utils import is_randomized_assignment_part

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.assessment.utils import copy_evaluation

from nti.app.products.courseware.resources.utils import get_course_filer

from nti.assessment import EVALUATION_INTERFACES

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.externalization.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporter

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID


@interface.implementer(ICourseSectionExporter)
class EvaluationsExporter(BaseSectionExporter):

    def _change_ntiid(self, ext_obj, salt=None):
        if isinstance(ext_obj, Mapping):
            # when not backing up make sure we take a hash of the current NTIID and
            # use it as the specific part for a new NTIID to make sure there are
            # fewer collisions when importing back
            for name in (NTIID, NTIID.lower()):
                ntiid = ext_obj.get(name)
                if ntiid:
                    ext_obj[name] = self.hash_ntiid(ntiid, salt)
            for value in ext_obj.values():
                self._change_ntiid(value, salt)
        elif isinstance(ext_obj, (list, tuple, set)):
            for value in ext_obj:
                self._change_ntiid(value, salt)

    def _output(self, course, target_filer=None, backup=True, salt=None):
        evaluations = ICourseEvaluations(course)
        source_filer = get_course_filer(course)

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
                export_evaluation_content(evaluation,
                                          source_filer,
                                          target_filer)
            ext_obj = to_external_object(evaluation,
                                         name="exporter",
                                         decorate=False)

            if IQuestionSet.providedBy(evaluation):
                ext_obj['Randomized'] = is_randomized_assignment(evaluation)
                ext_obj['RandomizedPartsType'] = is_randomized_assignment(evaluation)

            if IQAssignment.providedBy(evaluation):
                # This is an assignment, so we need to drill down
                # to its actual question set before we can
                # run the randomization decorator on it.
                for index, part in enumerate(evaluation.parts or ()):
                    qs = part.question_set
                    ext_part_obj = ext_obj['parts'][index]
                    ext_part_obj['Randomized'] = is_randomized_assignment(qs)
                    ext_part_obj['RandomizedPartsType'] = is_randomized_assignment_part(qs)

            if not backup:
                self._change_ntiid(ext_obj, salt)
            return ext_obj

        ordered = sorted(evaluations.values(), key=_get_key)
        return map(_ext, ordered)

    def externalize(self, context, filer=None, backup=True, salt=None):
        result = LocatedExternalDict()
        course = ICourseInstance(context)
        items = self._output(course,
                             target_filer=filer,
                             backup=backup,
                             salt=salt)
        if items:  # check
            result[ITEMS] = items
        return result

    def export(self, context, filer, backup=True, salt=None):
        course = ICourseInstance(context)
        courses = get_course_hierarchy(course)
        for course in courses:
            bucket = self.course_bucket(course)
            result = self.externalize(course, filer, backup, salt)
            if result:  # check
                source = self.dump(result)
                filer.save("evaluation_index.json", source, bucket=bucket,
                           contentType="application/json", overwrite=True)
        return result
