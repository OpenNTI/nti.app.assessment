#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from nti.assessment.interfaces import IQuestionSet

from nti.externalization.interfaces import IExternalObjectDecorator

from nti.externalization.singleton import Singleton

logger = __import__('logging').getLogger(__name__)


@component.adapter(IQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _NTIQuestionSetCountDecorator(Singleton):

    def decorateExternalObject(self, original, external):
        external.pop('question_count', None)
        question_count = getattr(original, 'draw', None) \
                      or len(original.questions)
        external['question-count'] = str(question_count)
