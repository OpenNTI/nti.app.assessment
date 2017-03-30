#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import copy
import uuid

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.security.interfaces import IPrincipal

from nti.app.assessment.common import make_evaluation_ntiid

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import import_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.authentication import get_remote_user

from nti.app.products.courseware.resources.utils import get_course_filer

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation

from nti.cabinet.filer import transfer_to_native_file

from nti.coremetadata.utils import current_principal

from nti.contentlibrary.interfaces import IFilesystemBucket

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter
from nti.contenttypes.courses.interfaces import ICourseEvaluationImporter

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.coremetadata.interfaces import ICalendarPublishable

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.property.property import Lazy

from nti.recorder.interfaces import IRecordable

from nti.recorder.record import copy_transaction_history

ITEMS = StandardExternalFields.ITEMS


@interface.implementer(ICourseSectionImporter, ICourseEvaluationImporter)
class EvaluationsImporter(BaseSectionImporter):

    EVALUATION_INDEX = "evaluation_index.json"

    @property
    def _extra(self):
        return str(uuid.uuid4()).split('-')[0].upper()

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

    def is_new(self, obj, course):
        ntiid = self.get_ntiid(obj)
        provided = iface_of_assessment(obj)
        evaluations = ICourseEvaluations(course)
        return  not ntiid \
            or (    ntiid not in evaluations
                and component.queryUtility(provided, name=ntiid) is None)

    def store_evaluation(self, obj, course):
        principal = self.current_principal
        ntiid = self.get_ntiid(obj)
        if not ntiid:
            provided = iface_of_assessment(obj)
            obj.ntiid = make_evaluation_ntiid(provided, extra=self._extra)
        obj.creator = principal.id  # always seet a creator
        evaluations = ICourseEvaluations(course)
        if ntiid not in evaluations:
            lifecycleevent.created(obj)
        # gain intid or replace provided the object is the same
        evaluations[obj.ntiid] = obj
        interface.alsoProvides(obj, IQEditableEvaluation)  # mark as editable
        return obj

    def get_registered_evaluation(self, obj, course, check_locked=False):
        ntiid = self.get_ntiid(obj)
        evaluations = ICourseEvaluations(course)
        if ntiid in evaluations:  # replace
            old = evaluations[ntiid]
            if not check_locked or not self.is_locked(obj):
                copy_transaction_history(old, obj)
                obj = evaluations.replace(old, obj, event=False)
            else:
                obj = old
            # mark as editable
            interface.alsoProvides(obj, IQEditableEvaluation)
        else:
            provided = iface_of_assessment(obj)
            obj = component.getUtility(provided, name=ntiid)
        return obj

    def handle_question(self, the_object, course, check_locked=False):
        if self.is_new(the_object, course):
            the_object = self.store_evaluation(the_object, course)
        else:
            the_object = self.get_registered_evaluation(the_object,
                                                        course,
                                                        check_locked)
        [p.ntiid for p in the_object.parts or ()]  # set auto part NTIIDs
        return the_object

    def handle_poll(self, the_object, course, check_locked=False):
        if self.is_new(the_object, course):
            the_object = self.store_evaluation(the_object, course)
        else:
            the_object = self.get_registered_evaluation(the_object,
                                                        course,
                                                        check_locked)
        [p.ntiid for p in the_object.parts or ()]  # set auto part NTIIDs
        return the_object

    def handle_question_set(self, the_object, course, check_locked=False):
        if not self.is_new(the_object, course):
            the_object = self.get_registered_evaluation(the_object,
                                                        course,
                                                        check_locked)
        if not check_locked or not self.is_locked(the_object):
            questions = indexed_iter()  # replace questions
            for question in the_object.questions or ():
                question = self.handle_question(question,
                                                course,
                                                check_locked)
                questions.append(question)
            the_object.questions = questions
            the_object = self.store_evaluation(the_object, course)
        return the_object

    def handle_survey(self, the_object, course, check_locked=False):
        if not self.is_new(the_object, course):
            the_object = self.get_registered_evaluation(the_object,
                                                        course,
                                                        check_locked)
        if not check_locked or not self.is_locked(the_object):
            questions = indexed_iter()  # replace polls
            for poll in the_object.questions or ():
                poll = self.handle_poll(poll, course)
                questions.append(poll)
            the_object.questions = questions
            the_object = self.store_evaluation(the_object, course)
        return the_object

    def handle_assignment_part(self, part, course, check_locked=False):
        question_set = self.handle_question_set(part.question_set,
                                                course,
                                                check_locked)
        part.question_set = question_set  # replace is safe in part
        return part

    def handle_assignment(self, the_object, course, check_locked=False):
        if not self.is_new(the_object, course):
            the_object = self.get_registered_evaluation(the_object,
                                                        course,
                                                        check_locked)
        if not check_locked or not self.is_locked(the_object):
            parts = indexed_iter()
            for part in the_object.parts or ():
                part = self.handle_assignment_part(part,
                                                   course,
                                                   check_locked)
                parts.append(part)
            the_object.parts = parts
            the_object = self.store_evaluation(the_object, course)
        [p.ntiid for p in the_object.parts or ()]  # set auto part NTIIDs
        return the_object

    def handle_evaluation(self, the_object, source, course,
                          check_locked=False, source_filer=None):
        if IQuestion.providedBy(the_object):
            result = self.handle_question(the_object,
                                          course,
                                          check_locked)
        elif IQPoll.providedBy(the_object):
            result = self.handle_poll(the_object,
                                      course,
                                      check_locked)
        elif IQuestionSet.providedBy(the_object):
            result = self.handle_question_set(the_object,
                                              course,
                                              check_locked)
        elif IQSurvey.providedBy(the_object):
            result = self.handle_survey(the_object,
                                        course,
                                        check_locked)
        elif IQAssignment.providedBy(the_object):
            result = self.handle_assignment(the_object,
                                            course,
                                            check_locked)
        else:
            result = the_object

        if      IQEditableEvaluation.providedBy(result) \
            and (not check_locked or not self.is_locked(result)):
            # course is the evaluation home
            result.__home__ = course
            remoteUser = get_remote_user()
            target_filer = get_course_filer(course, remoteUser)
            # parse content fields and load sources
            import_evaluation_content(result,
                                      context=course,
                                      source_filer=source_filer,
                                      target_filer=target_filer)
            # always register
            register_context(result, force=True)

        is_published = source.get('isPublished')
        if is_published and (not check_locked or not self.is_locked(result)):
            if ICalendarPublishable.providedBy(result):
                result.publish(start=result.publishBeginning,
                               end=result.publishEnding,
                               event=False)
            else:
                result.publish(event=False)

        locked = source.get('isLocked')
        if      locked \
            and IRecordable.providedBy(result) \
            and (not check_locked or not self.is_locked(result)):
            the_object.lock(event=False)
            lifecycleevent.modified(result)
        return result

    def handle_course_items(self, items, course,
                            check_locked=False, source_filer=None):
        for ext_obj in items or ():
            source = copy.deepcopy(ext_obj)
            factory = find_factory_for(ext_obj)
            the_object = factory()
            update_from_external_object(the_object, ext_obj, notify=False)
            self.handle_evaluation(the_object,
                                   source=source,
                                   course=course,
                                   check_locked=check_locked,
                                   source_filer=source_filer)

    def process_source(self, course, source, check_locked=True, filer=None):
        source = self.load(source)
        items = source.get(ITEMS)
        self.handle_course_items(items, course, check_locked, filer)

    def do_import(self, course, filer, writeout=True):
        href = self.course_bucket_path(course) + self.EVALUATION_INDEX
        source = self.safe_get(filer, href)
        if source is not None:
            self.process_source(course, source, False, filer)
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
