#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.assessment.interfaces import IQEditableEvalutation

from nti.publishing.interfaces import IPublishable
from nti.publishing.interfaces import IPublishables


@interface.implementer(IPublishables)
class EvaluationPublishables(object):

    __slots__ = ()

    def iter_objects(self):
        for _, obj in component.getUtilitiesFor(IQEditableEvalutation):
            if IPublishable.providedBy(obj):
                yield obj
