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

from nti.assessment.interfaces import IQEvaluation

from nti.contenttypes.completion.interfaces import ICompletables
from nti.contenttypes.completion.interfaces import ICompletableItem

logger = __import__('logging').getLogger(__name__)


@interface.implementer(ICompletables)
class EvaluationCompletables(object):

    __slots__ = ()

    def iter_objects(self):
        for unused_name, obj in component.getUtilitiesFor(IQEvaluation):
            if ICompletableItem.providedBy(obj):
                yield obj
