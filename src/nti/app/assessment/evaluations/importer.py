#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import copy
import uuid

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.cachedescriptors.property import Lazy

from zope.security.interfaces import IPrincipal

from nti.app.assessment.common.utils import make_evaluation_ntiid

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import import_evaluation_content

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.authentication import get_remote_user

from nti.app.base.abstract_views import get_source_filer

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation

from nti.assessment.randomized.interfaces import IRandomizedQuestionSet
from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.cabinet.filer import transfer_to_native_file

from nti.coremetadata.utils import current_principal

from nti.contentlibrary.interfaces import IFilesystemBucket
from nti.contentlibrary.interfaces import IEditableContentPackage
from nti.contentlibrary.interfaces import IContentPackageImporterUpdater

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter
from nti.contenttypes.courses.interfaces import ICourseEvaluationImporter

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.publishing.interfaces import ICalendarPublishable

from nti.recorder.interfaces import IRecordable

ITEMS = StandardExternalFields.ITEMS


class EvaluationsImporterMixin(object):

    @property
    def _extra(self):
        return str(uuid.uuid4().get_time_low())

    def is_locked(self, obj):
        return IRecordable.providedBy(obj) and obj.is_locked()

    @Lazy
    def current_principal(self):
        remoteUser = IPrincipal(get_remote_user(), None)
        if remoteUser is None:
            remoteUser = current_principal()
        return remoteUser

    def get_ntiid(self, obj):
        return getattr(obj, 'ntiid', None)

    def is_new(self, obj, context):
        ntiid = self.get_ntiid(obj)
        provided = iface_of_assessment(obj)
        evaluations = IQEvaluations(context)
        return not ntiid \
            or (    ntiid not in evaluations
                and component.queryUtility(provided, name=ntiid) is None)

    def store_evaluation(self, obj, context):
        principal = self.current_principal
        ntiid = self.get_ntiid(obj)
        if not ntiid:
            provided = iface_of_assessment(obj)
            obj.ntiid = make_evaluation_ntiid(provided, extra=self._extra)
        obj.creator = principal.id  # always set a creator
        evaluations = IQEvaluations(context)
        if ntiid not in evaluations:
            lifecycleevent.created(obj)
        # gain intid or replace provided the object is the same
        evaluations[obj.ntiid] = obj
        interface.alsoProvides(obj, IQEditableEvaluation)  # mark as editable
        return obj

    def get_registered_evaluation(self, obj, context):
        ntiid = self.get_ntiid(obj)
        evaluations = IQEvaluations(context)
        if ntiid in evaluations:
            # XXX: Don't replace since we are neither doing structural
            # validations nor checking for submissions
            obj = evaluations[ntiid]
        else:
            provided = iface_of_assessment(obj)
            obj = component.getUtility(provided, name=ntiid)
        return obj

    def handle_question(self, the_object, context):
        if self.is_new(the_object, context):
            the_object = self.store_evaluation(the_object, context)
        else:
            the_object = self.get_registered_evaluation(the_object, context)
        [p.ntiid for p in the_object.parts or ()]  # set auto part NTIIDs
        return the_object

    def handle_poll(self, the_object, context):
        if self.is_new(the_object, context):
            the_object = self.store_evaluation(the_object, context)
        else:
            the_object = self.get_registered_evaluation(the_object, context)
        [p.ntiid for p in the_object.parts or ()]  # set auto part NTIIDs
        return the_object

    def canonicalize_question_set(self, the_object, context):
        questions = indexed_iter()  # replace questions
        for question in the_object.questions or ():
            question = self.handle_question(question, context)
            questions.append(question)
        the_object.questions = questions

    def handle_question_set(self, the_object, source, context):
        is_new = self.is_new(the_object, context)
        if not is_new:
            the_object = self.get_registered_evaluation(the_object, context)
        else:
            self.canonicalize_question_set(the_object, context)
            for name, provided in (('Randomized', IRandomizedQuestionSet),
                                   ('RandomizedPartsType', IRandomizedPartsContainer)):
                value = source.get(name) if source else False
                if value:
                    interface.alsoProvides(the_object, provided)
            the_object = self.store_evaluation(the_object, context)
        return the_object

    def canonicalize_survey(self, the_object, context):
        questions = indexed_iter()  # replace polls
        for poll in the_object.questions or ():
            poll = self.handle_poll(poll, context, False)
            questions.append(poll)
        the_object.questions = questions

    def handle_survey(self, the_object, context):
        is_new = self.is_new(the_object, context)
        if not is_new:
            the_object = self.get_registered_evaluation(the_object, context)
        else:
            self.canonicalize_survey(the_object, context)
            the_object = self.store_evaluation(the_object, context)
        return the_object

    def handle_assignment_part(self, part, source, context):
        ext_obj = source.get('question_set') if source else None
        question_set = self.handle_question_set(part.question_set,
                                                ext_obj,
                                                context)
        part.question_set = question_set  # replace is safe in part
        return part

    def canonicalize_assignment(self, the_object, context, source=None):
        parts = indexed_iter()
        for index, part in enumerate(the_object.parts) or ():
            ext_obj = source['parts'][index] if source else None
            part = self.handle_assignment_part(part, ext_obj, context)
            parts.append(part)
        the_object.parts = parts

    def handle_assignment(self, the_object, source, context):
        is_new = self.is_new(the_object, context)
        if not is_new:
            the_object = self.get_registered_evaluation(the_object, context)
        else:
            self.canonicalize_assignment(the_object, context, source)
            the_object = self.store_evaluation(the_object, context)
        [p.ntiid for p in the_object.parts or ()]  # set auto part NTIIDs
        return the_object

    def publish_evaluation(self, the_object, source=None, unused_context=None):
        is_published = source.get('isPublished') if source else False
        if is_published:
            if ICalendarPublishable.providedBy(the_object):
                the_object.publish(start=the_object.publishBeginning,
                                   end=the_object.publishEnding,
                                   event=False)
            else:
                the_object.publish(event=False)
        return the_object

    def handle_evaluation(self, the_object, source, context, filer=None):
        if IQuestion.providedBy(the_object):
            result = self.handle_question(the_object, context)
        elif IQPoll.providedBy(the_object):
            result = self.handle_poll(the_object, context)
        elif IQuestionSet.providedBy(the_object):
            result = self.handle_question_set(the_object, source, context)
        elif IQSurvey.providedBy(the_object):
            result = self.handle_survey(the_object, context)
        elif IQAssignment.providedBy(the_object):
            result = self.handle_assignment(the_object, source, context)
        else:
            result = the_object

        if IQEditableEvaluation.providedBy(result):
            # course is the evaluation home
            result.__home__ = context
            remoteUser = get_remote_user()
            target_filer = get_source_filer(context, remoteUser)
            # parse content fields and load sources
            import_evaluation_content(result,
                                      context=context,
                                      source_filer=filer,
                                      target_filer=target_filer)
            # always register
            register_context(result, force=True)

        self.publish_evaluation(result, source, context)

        locked = source.get('isLocked') if source else False
        if      locked \
            and IRecordable.providedBy(result):
            the_object.lock(event=False)
            lifecycleevent.modified(result)
        return result

    def handle_evaluation_items(self, items, context, filer=None):
        for ext_obj in items or ():
            source = copy.deepcopy(ext_obj)
            factory = find_factory_for(ext_obj)
            the_object = factory()
            update_from_external_object(the_object, ext_obj, notify=False)
            self.handle_evaluation(the_object, source, context, filer)


@interface.implementer(ICourseSectionImporter, ICourseEvaluationImporter)
class EvaluationsImporter(EvaluationsImporterMixin, BaseSectionImporter):

    EVALUATION_INDEX = "evaluation_index.json"

    def handle_course_items(self, items, course, filer=None):
        return self.handle_evaluation_items(items, course, filer)

    def process_source(self, course, source, filer=None):
        source = self.load(source)
        items = source.get(ITEMS)
        self.handle_course_items(items, course, filer)

    def do_import(self, course, filer, writeout=True):
        href = self.course_bucket_path(course) + self.EVALUATION_INDEX
        source = self.safe_get(filer, href)
        if source is not None:
            self.process_source(course, source, filer)
            # save source
            if writeout and IFilesystemBucket.providedBy(course.root):
                source = self.safe_get(filer, href)  # reload
                self.makedirs(course.root.absolute_path)  # create
                new_path = os.path.join(course.root.absolute_path,
                                        self.EVALUATION_INDEX)
                transfer_to_native_file(source, new_path)
            return True
        return False

    def process(self, context, filer, writeout=True):
        course = ICourseInstance(context)
        result = self.do_import(course, filer, writeout)
        for subinstance in get_course_subinstances(course):
            result = self.do_import(subinstance, filer, writeout) or result
        return result


@component.adapter(IEditableContentPackage)
@interface.implementer(IContentPackageImporterUpdater)
class _EditableContentPackageImporterUpdater(EvaluationsImporterMixin):

    def __init__(self, *args):
        pass
    
    def publish_evaluation(self, the_object, source=None, context=None):
        if context is not None and context.is_published():
            EvaluationsImporterMixin.publish_evaluation(self, the_object, 
                                                        source, context)
        return the_object

    def updateFromExternalObject(self, package, externalObject, *args, **kwargs):
        evaluations = externalObject.get('Evaluations')
        if evaluations:
            items = evaluations[ITEMS]
            self.handle_evaluation_items(items, package, kwargs.get('filer'))
