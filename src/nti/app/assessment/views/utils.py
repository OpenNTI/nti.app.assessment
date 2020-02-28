#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import six

from nti.contentfragments.interfaces import IPlainTextContentFragment

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


def _handle_non_gradable_connecting_part(user_sub_part, poll, part_idx):
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


def _handle_multiple_choice_multiple_answer(user_sub_part, poll_or_question, part_idx):
    response_values = user_sub_part
    part_values = poll_or_question.parts[part_idx].choices
    result = [
        plain_text(part_values[int(k)]) for k in response_values
    ]
    return _display_list(result)


def _handle_multiple_choice_part(user_sub_part, poll_or_question, part_idx):
    part_values = poll_or_question.parts[part_idx].choices
    return plain_text(part_values[int(user_sub_part)])


def _handle_modeled_content_part(user_sub_part, unused_poll_or_question, unused_part_idx):
    return plain_text(' '.join(user_sub_part.value))


def _handle_free_response_part(user_sub_part, unused_poll_or_question, unused_part_idx):
    return plain_text(user_sub_part)
