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

from nti.recorder.interfaces import IRecordable
from nti.recorder.interfaces import IRecordables

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IRecordables)
class EvaluationRecordables(object):

    __slots__ = ()

    def iter_objects(self):
        for _, obj in component.getUtilitiesFor(IQEvaluation):
            if IRecordable.providedBy(obj):
                yield obj
