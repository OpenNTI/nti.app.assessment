#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import sys

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from ZODB.POSException import POSError

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.assessed import set_parent
from nti.app.assessment.common.assessed import get_part_value

from nti.app.base.abstract_views import get_source

from nti.app.contentfile import transfer_data

from nti.app.externalization.error import raise_json_error

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQFilePart
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IInternalUploadedFileRef

from nti.base.interfaces import IFile

logger = __import__('logging').getLogger(__name__)


def check_max_size(part, max_file_size=None):
    size = part.size
    max_file_size = max_file_size or sys.maxint
    if size > max_file_size:
        raise_json_error(get_current_request(),
                         hexc.HTTPUnprocessableEntity,
                         {
                             'message': _(u"Max file size exceeded."),
                         },
                         None)
    return part


def check_upload_files(submission):
    for question_set in submission.parts:
        for sub_question in question_set.questions:
            question = component.getUtility(IQuestion, sub_question.questionId)
            for part, sub_part in zip(question.parts, sub_question.parts):
                part_value = get_part_value(sub_part)
                if not IFile.providedBy(part_value):
                    continue

                if not IQFilePart.providedBy(part):
                    msg = 'Invalid submission. Expected a IQFilePart, ' \
                          'instead it found %s' % part
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': msg,
                                     },
                                     None)
                max_size = part.max_file_size
                check_max_size(part_value, max_size)
    return submission


def read_multipart_sources(submission, request):
    for question_set in submission.parts:
        for sub_question in question_set.questions:
            question = component.getUtility(IQuestion, sub_question.questionId)
            for part, sub_part in zip(question.parts, sub_question.parts):
                part_value = get_part_value(sub_part)
                if not IFile.providedBy(part_value):
                    continue

                if not IQFilePart.providedBy(part):
                    msg = 'Invalid submission. Expected a IQFilePart, ' \
                          'instead it found %s' % part
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': msg,
                                     },
                                     None)
                max_size = part.max_file_size
                if part_value.size > 0:
                    check_max_size(part_value, max_size)

                if not part_value.name:
                    msg = _(u'No name was given to uploded file.')
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': msg,
                                     },
                                     None)

                source = get_source(request, part_value.name)
                if source is None:
                    msg = 'Could not find data for file %s' % part_value.name
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': msg,
                                     },
                                    None)

                # copy data
                transfer_data(source, part_value)
    return submission


def set_poll_submission_lineage(submission):
    for submitted_question_part in submission.parts:
        set_parent(submitted_question_part, submission)
    return submission


def set_survey_submission_lineage(submission):
    for submitted_question in submission.questions:
        set_parent(submitted_question, submission)
        set_poll_submission_lineage(submitted_question)
    return submission


def set_inquiry_submission_lineage(submission):
    if IQPollSubmission.providedBy(submission):
        set_poll_submission_lineage(submission)
    elif IQSurveySubmission.providedBy(submission):
        set_survey_submission_lineage(submission)
    return submission

class _LazyQuestionsIndex(object):

    @Lazy
    def qset_index(self):
        return { q.questionId: q for q in self.question_set.questions }

    def __init__(self, question_set):
        self.question_set = question_set

    def __getitem__(self, key):
        return self.qset_index[key]

def transfer_submission_file_data(source, target,  force=False):
    """
    Search for previously uploaded files and make them part of the
    new submission if nothing has changed.

    :param source Source submission
    :param target Target submission
    """

    def _is_internal(source):
        if not IFile.providedBy(source):
            return False
        if force:
            return True
        else:
            filename = getattr(source, 'filename', None)
            size = getattr(source, 'size', None) or source.getSize()
            result = IInternalUploadedFileRef.providedBy(source) \
                  or (not filename and size == 0)
            return result

    # extra check
    if source is None or target is None:
        return target

    for question_set in target.parts:
        try:
            # make sure we have a question set
            old_question_set = source.get(question_set.questionSetId)
            if old_question_set is None:
                continue

            # Looking up a question by questionId in the old questions
            # (QuestionSetSubmission.get) requires iterating the
            # question set. Taking a pass to create an index here is
            # much faster than getting the question by id inside the
            # loop (n^2).
            old_questions = _LazyQuestionsIndex(old_question_set)
            
            for question in question_set.questions:
                # For each question we have, iterate the question
                # parts, if we have a part that is an internal file
                # (_is_internal(part) == True) then look for the same
                # part in the old submission and move it to us if found

                # Parts of a question are ordered
                for idx, new_part in enumerate(question.parts or ()):

                    # Can we do an interface check here first that would
                    # allow us to shortcircuit this iteration?
                    new_part_value = get_part_value(new_part)
                    if not _is_internal(new_part_value):
                        continue

                    # Ok, does our old submission have a matching part value
                    # that provides file
                    try:
                        # TODO Are questions on the set/setsubmission meant to
                        # be an array such that we can just line
                        # indexes up like we do for question parts?
                        old_question = old_questions[question.questionId]
                        old_part = old_question[idx]
                        old_part_value = get_part_value(old_part)
                    except KeyError:
                        # No question by that id in the old_questions
                        continue
                    except IndexError:
                        # No part in the question that lines up
                        continue

                    if IFile.providedBy(old_part_value):
                        new_part_value.data = old_part_value.data
                        new_part_value.filename = old_part_value.filename
                        new_part_value.contentType = old_part_value.contentType
                        name = getattr(old_part_value, 'name', None) 
                        new_part_value.name = name or part_value.filename
                        interface.noLongerProvides(new_part_value,
                                                   IInternalUploadedFileRef)
        except (POSError, TypeError):
            logger.exception("Failed to transfer data from savepoints")
            break
    return target
