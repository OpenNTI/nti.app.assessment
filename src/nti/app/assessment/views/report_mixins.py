#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import csv
import six
import random

from collections import OrderedDict

from io import BytesIO

from pyramid import httpexceptions as hexc

from zope.location import LocationIterator

from nti.contentfragments.interfaces import IPlainTextContentFragment

from nti.assessment.randomized import shuffle_list
from nti.assessment.randomized.interfaces import IQRandomizedPart

from nti.app.assessment.views import MessageFactory as _

from nti.app.externalization.error import raise_json_error

from nti.appserver.pyramid_authorization import has_permission

from nti.contenttypes.courses.utils import is_course_instructor
from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver import authorization as nauth

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.dataserver.authorization_acl import has_permission as _ds_has_permission

logger = __import__('logging').getLogger(__name__)


def plain_text(s):
    # turn to plain text and to unicode
    result = IPlainTextContentFragment(s) if s else u''
    return _tx_string(result.strip())


def _tx_string(s):
    if s is not None and isinstance(s, six.text_type):
        s = s.encode('utf-8')
    return s


def _display_list(data):
    result = []
    for item in data[:-1]:
        result.append('%s, ' % item)
    if data:
        result.append('%s' % data[-1])
    return u''.join(result)


def _wordbank(part):
    wordbank = None
    for obj in LocationIterator(part):
        parent_bank = getattr(obj, 'wordbank', None)
        if not wordbank:
            wordbank = parent_bank
        elif parent_bank:
            wordbank = wordbank + parent_bank
    return wordbank


def _handle_non_gradable_connecting_part(user_sub_part, poll, part_idx, generator=None):
    # need this to be sorted by value. Since the response
    # values come from a dictionary, they may not be in the right order
    # otherwise. We need to make sure to assign the correct label
    # for each response.
    response_values = sorted(user_sub_part.items(), key=lambda x: x[1])
    part_values = poll.parts[part_idx].values
    part_labels = [plain_text(x) for x in part_values]
    # We look up by key from the response values in order
    # to get the label for this choice.
    result = [part_labels[int(k[0])] for k in response_values]
    return _display_list(result)


def _handle_non_gradable_ordering_part(user_sub_part, question, part_idx, generator=None):
    values = [plain_text(x) for x in question.parts[part_idx].values]

    if generator is not None:
        values = shuffle_list(generator, values)

    user_sub_part = sorted(user_sub_part.items(), key=lambda x: x[0])
    result = []
    # convert to int dict like grader?
    result = [values[idx] for _, idx in user_sub_part]
    return ",".join(result)


def _handle_non_gradable_matching_part(user_sub_part, question, part_idx, generator=None):
    labels = [plain_text(x) for x in question.parts[part_idx].labels]
    values = [plain_text(x) for x in question.parts[part_idx].values]

    if generator is not None:
        values = shuffle_list(generator, values)

    user_sub_part = sorted(user_sub_part.items(), key=lambda x: x[0])
    result = []
    # convert to int dict like grader?
    for label_idx, value_idx in user_sub_part:
        result.append("%s=%s" % (labels[int(label_idx)], values[value_idx]))
    return ",".join(result)


def _handle_multiple_choice_multiple_answer(user_sub_part, poll_or_question, part_idx, generator=None):
    response_values = user_sub_part
    part_values = poll_or_question.parts[part_idx].choices

    if generator is not None:
        part_values = shuffle_list(generator, list(part_values))

    result = [
        plain_text(part_values[int(k)]) for k in response_values
    ]
    return _display_list(result)


def _handle_multiple_choice_part(user_sub_part, poll_or_question, part_idx, generator=None):
    part_values = poll_or_question.parts[part_idx].choices
    if generator is not None:
        part_values = shuffle_list(generator, list(part_values))
    return plain_text(part_values[int(user_sub_part)])


def _handle_fill_in_the_blank_with_work_bank(user_sub_part, question, part_idx, generator=None):
    wordbank = _wordbank(question.parts[part_idx]) or {}
    user_sub_part = sorted(user_sub_part.items(), key=lambda x: x[0])
    result = []
    for name, idx in user_sub_part:
        # Only return those filled in,
        if idx is not None:
            entry = wordbank.get(idx)
            result.append("%s=%s" % (name, entry.word or entry.wid if entry else idx))
    return ','.join(result)


def _handle_fill_in_the_blank_short_answer(user_sub_part, question, part_idx, generator=None):
    result = [ "%s=%s" % (name, value) for name, value in user_sub_part.items() if value is not None]
    return ','.join(result)


def _handle_modeled_content_part(user_sub_part, unused_poll_or_question, unused_part_idx, unused_generator=None):
    return plain_text(' '.join(user_sub_part.value))


def _handle_free_response_part(user_sub_part, unused_poll_or_question, unused_part_idx, unused_generator=None):
    return plain_text(user_sub_part)


class AssessmentCSVReportMixin(object):

    question_functions = ()

    course = None

    def _generator(self, part, attempt=None, user=None):
        # Only shuffle parts if the user is not an instructor or an editor,
        # See nti.app.assessment.decorators.randomized._AbstractNonEditorRandomizingDecorator
        if not user or not attempt:
            return None

        if IQRandomizedPart.providedBy(part) \
            and not is_course_instructor_or_editor(self.course, user) \
            and not _ds_has_permission(ACT_CONTENT_EDIT, part, user.username):
            return random.Random(attempt.Seed)
        return None

    def _get_function_for_question_type(self, poll_or_question_part):
        # look through mapping to find a match
        for iface, factory in self.question_functions:
            if iface.providedBy(poll_or_question_part):
                return factory
        # return None if we can't find a match for this question type.
        return None

    def _get_user_question_results(self, question, question_submission, attempt=None, user=None):
        # A question may have multiple parts, so we need to go through
        # each part. We look at the question parts from the user's
        # submission to get their responses for each part, and we also
        # look at the question parts from the poll/question to get labels for the
        # user's response, if applicable.
        user_question_results = []
        for part_idx, part in enumerate(zip(question_submission.parts, question.parts)):
            question_part_submission, question_part = part

            result = ''
            if question_part_submission is None:
                # If the question part is None, the user did not respond
                # to this question
                user_question_results.append(result)
                continue

            # Get the correct function for this question type, then use
            # that to calculate the result.
            question_handler = self._get_function_for_question_type(question_part)
            if question_handler is not None:
                generator = self._generator(question.parts[part_idx], attempt, user)
                result = question_handler(question_part_submission,
                                          question,
                                          part_idx,
                                          generator)
            user_question_results.append(result)

        assert len(user_question_results) == len(question.parts)
        return user_question_results

    def _check_permission(self):
        # only instructors or admins should be able to view this.
        if not (is_course_instructor(self.course, self.remoteUser)
                or has_permission(nauth.ACT_NTI_ADMIN, self.course, self.request)):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot access to this report.")
                             },
                             None)

    def _get_filename(self):
        return self.context.title or self.context.id

    def _get_question_header(self, question, prefix=None):
        header = []
        if len(question.parts) > 1:
            # If the question has more than one part, we need to
            # create a column for each part of the question.
            for part in question.parts:
                col = plain_text(question.content) + ": " + plain_text(part.content)
                header.append("{}: {}".format(prefix, col) if prefix else col)
        else:
            content = plain_text(question.content)
            part_content = plain_text(question.parts[0].content) if question.parts else ''
            if content and part_content:
                content = '%s: %s' % (content, part_content)
            elif part_content:
                content = part_content
            header.append("{}: {}".format(prefix, content) if prefix else content)
        return header

    def _get_header_row(self, question_order):
        raise NotImplementedError

    def _get_user_rows(self, question_order, column_count):
        raise NotImplementedError

    def _write_response(self):
        self._check_permission()

        stream = BytesIO()
        csv_writer = csv.writer(stream)

        question_order = OrderedDict()
        header_row = self._get_header_row(question_order)

        csv_writer.writerow(header_row)

        column_count = len(header_row)

        user_rows = self._get_user_rows(question_order, column_count)
        for row in user_rows:
            csv_writer.writerow(row)

        stream.flush()
        stream.seek(0)
        self.request.response.body_file = stream
        self.request.response.content_type = 'text/csv; charset=UTF-8'
        self.request.response.content_disposition = 'attachment; filename="%s"' % self._get_filename()
        return self.request.response
