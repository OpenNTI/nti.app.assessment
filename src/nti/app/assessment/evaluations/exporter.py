#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from collections import Mapping

from zope import component
from zope import interface

from nti.app.assessment.common.evaluations import get_course_evaluations

from nti.app.assessment.evaluations.interfaces import ICourseEvaluationsSectionExporter

from nti.app.assessment.evaluations.utils import course_discussions
from nti.app.assessment.evaluations.utils import sort_evaluation_key

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.authentication import get_remote_user

from nti.app.base.abstract_views import get_source_filer

from nti.assessment.common import is_randomized_question_set
from nti.assessment.common import is_randomized_parts_container

from nti.assessment.externalization import EvalWithPartsExporter

from nti.assessment.interfaces import DISCUSSION_ASSIGNMENT_MIME_TYPE

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQDiscussionAssignment

from nti.contentlibrary.interfaces import IEditableContentPackage
from nti.contentlibrary.interfaces import IContentPackageExporterDecorator

from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussion
from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussionTopic
from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussionsSectionExporter

from nti.contenttypes.courses.discussions.exporter import user_topic_file_name
from nti.contenttypes.courses.discussions.exporter import user_topic_dicussion_id
from nti.contenttypes.courses.discussions.exporter import export_user_topic_as_discussion

from nti.contenttypes.courses.discussions.parser import path_to_discussions

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionExporterExecutedEvent

from nti.contenttypes.courses.exporter import BaseSectionExporter

from nti.contenttypes.courses.utils import get_course_hierarchy

from nti.dataserver.contenttypes.forums.interfaces import ITopic
from nti.dataserver.contenttypes.forums.interfaces import IHeadlinePost

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import StandardInternalFields
from nti.externalization.interfaces import IInternalObjectExternalizer

from nti.externalization.proxy import removeAllProxies

from nti.ntiids.ntiids import hash_ntiid
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

INTERNAL_NTIID = StandardInternalFields.NTIID

logger = __import__('logging').getLogger(__name__)


class EvaluationsExporterMixin(object):

    def change_evaluation_ntiid(self, ext_obj, salt=None):
        if isinstance(ext_obj, Mapping):
            # when not backing up make sure we take a hash of the current NTIID and
            # use it as the specific part for a new NTIID to make sure there are
            # fewer collisions when importing back
            for name in (NTIID, INTERNAL_NTIID):
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

    def do_evaluations_export(self, context, backup=True, salt=None, filer=None):
        if filer is None:
            filer = get_source_filer(context, get_remote_user())

        def _ext(item):
            evaluation = removeAllProxies(item)
            ext_obj = to_external_object(evaluation,
                                         name="exporter",
                                         decorate=False)

            if IQuestionSet.providedBy(evaluation):
                ext_obj['Randomized'] = is_randomized_question_set(evaluation)
                ext_obj['RandomizedPartsType'] = is_randomized_parts_container(evaluation)

            if      IQDiscussionAssignment.providedBy(evaluation) \
                and not ext_obj.get('discussion_ntiid'):
                # If our discussion assignment does not point to a valid
                # discussion, exclude it.
                return

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

        ordered = sorted(self.evaluations(context), key=sort_evaluation_key)
        result = []
        for assessment_item in ordered:
            ext_item = _ext(assessment_item)
            if ext_item:
                result.append(ext_item)
        return result

    def export_evaluations(self, context, backup=True, salt=None, filer=None):
        result = LocatedExternalDict()
        items = self.do_evaluations_export(context, backup, salt, filer)
        if items:  # check
            result[ITEMS] = items
            result[TOTAL] = result[ITEM_COUNT] = len(items)
        return result


@interface.implementer(ICourseEvaluationsSectionExporter)
class EvaluationsExporter(EvaluationsExporterMixin, BaseSectionExporter):

    def externalize(self, context, backup=True, salt=None, filer=None):
        course = ICourseInstance(context)
        return self.export_evaluations(course, backup, salt, filer)

    def export(self, context, filer, backup=True, salt=None):
        course = ICourseInstance(context)
        for course in get_course_hierarchy(course):
            filer.default_bucket = bucket = self.course_bucket(course)
            result = self.externalize(course, backup, salt, filer)
            if result:  # check
                source = self.dump(result)
                filer.save("evaluation_index.json", source, bucket=bucket,
                           contentType="application/json", overwrite=True)
        return result


@component.adapter(IEditableContentPackage)
@interface.implementer(IContentPackageExporterDecorator)
class _EditableContentPackageExporterDecorator(EvaluationsExporterMixin):

    def __init__(self, *args):
        pass

    def decorateExternalObject(self, package, external, backup=True, salt=None, filer=None):
        evaluations = self.export_evaluations(package, backup, salt, filer)
        if evaluations:
            external['Evaluations'] = evaluations


@component.adapter(IQDiscussionAssignment)
@interface.implementer(IInternalObjectExternalizer)
class _DiscussionAssignmentExporter(EvalWithPartsExporter):

    def process_discussion(self, result, course):
        ntiid = self.evaluation.discussion_ntiid
        context = find_object_with_ntiid(ntiid)
        if context is not None:
            if ICourseDiscussion.providedBy(context):
                result['discussion_ntiid'] = context.id
            elif IHeadlinePost.providedBy(context):
                context = context.__parent__
            if ITopic.providedBy(context):
                name = context.__name__ # by definition
                discussions = course_discussions(course)
                discussion = discussions.get(name)
                if discussion is not None:
                    result['discussion_ntiid'] = discussion.id
                else:
                    result['discussion_ntiid'] = user_topic_dicussion_id(context)
        return result

    def toExternalObject(self, **kwargs):
        result = EvalWithPartsExporter.toExternalObject(self, **kwargs)
        course = find_interface(self.evaluation, ICourseInstance, strict=False)
        if course is not None:
            self.process_discussion(result, course)
        return result


def export_user_course_discussions(context, exporter, filer):
    result = []
    course = ICourseInstance(context)
    bucket = path_to_discussions(course)
    mimetypes = (DISCUSSION_ASSIGNMENT_MIME_TYPE,)
    for evaluation in get_course_evaluations(course, None, None, mimetypes, True):
        if not IQDiscussionAssignment.providedBy(evaluation):
            continue
        ntiid = evaluation.discussion_ntiid
        topic = find_object_with_ntiid(ntiid)
        if IHeadlinePost.providedBy(context):
            topic = context.__parent__
        if      ITopic.providedBy(topic) \
            and not ICourseDiscussionTopic.providedBy(topic):
            ext_obj = export_user_topic_as_discussion(topic)
            source = exporter.dump(ext_obj)
            name = user_topic_file_name(topic)
            filer.save(name, source, contentType="application/json",
                       bucket=bucket, overwrite=True)
            result.append(topic)
    return result


@component.adapter(ICourseInstance, ICourseSectionExporterExecutedEvent)
def _on_course_section_exported_event(context, event):
    filer = event.filer
    exporter = event.exporter
    if ICourseDiscussionsSectionExporter.providedBy(exporter) and filer is not None:
        logger.info("Exporting discussion assignment course discussions")
        export_user_course_discussions(context, exporter, filer)
    