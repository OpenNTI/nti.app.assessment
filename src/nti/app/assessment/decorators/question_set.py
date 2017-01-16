#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.assessment.interfaces import IQuestionSet

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator

from nti.externalization.singleton import SingletonDecorator

OID = StandardExternalFields.OID
LINKS = StandardExternalFields.LINKS


@component.adapter(IQuestionSet)
@interface.implementer(IExternalObjectDecorator)
class _NTIQuestionSetCountDecorator(object):

    __metaclass__ = SingletonDecorator

    def decorateExternalObject(self, original, external):
        external.pop('question_count', None)
        question_count =   getattr(original, 'draw', None) \
                        or len(original.questions)
        external[u'question-count'] = str(question_count)
