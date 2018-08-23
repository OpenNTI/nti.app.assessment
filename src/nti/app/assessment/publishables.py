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

from nti.assessment.interfaces import IQEditableEvalutation

from nti.publishing.interfaces import IPublishable
from nti.publishing.interfaces import IPublishables

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IPublishables)
class EvaluationPublishables(object):

    __slots__ = ()

    def iter_objects(self):
        for unused_name, obj in component.getUtilitiesFor(IQEditableEvalutation):
            if IPublishable.providedBy(obj):
                yield obj
