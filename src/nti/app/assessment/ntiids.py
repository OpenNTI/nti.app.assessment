#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NTIID support for assessments in the application.

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.assessment.interfaces import NTIID_TYPE

from nti.assessment.interfaces import IQEvaluation

from nti.ntiids.interfaces import INTIIDResolver

from nti.ntiids.ntiids import get_parts
from nti.ntiids.ntiids import make_ntiid
from nti.ntiids.ntiids import find_object_with_ntiid


@interface.implementer(INTIIDResolver)
class _EvaluationResolver(object):
    """
    A resolver for the :const:`nti.assessment.interfaces.NTIID_TYPE`
    value. This one single type of ntiid is used for questions,
    question sets, assignments, surveys and polls. We expect to be able to
    resolve these using the current component registry.
    """

    def resolve(self, ntiid):
        return component.queryUtility(IQEvaluation, name=ntiid)
_AssessmentResolver = _EvaluationResolver


@interface.implementer(INTIIDResolver)
class _EvaluationPartResolver(object):

    def resolve(self, ntiid):
        parts = get_parts(ntiid)
        specific = parts.specific[:parts.specific.rfind('.')]
        parent_ntiid = make_ntiid(date=parts.date,
                                  provider=parts.provider,
                                  nttype=NTIID_TYPE,
                                  specific=specific)
        parent = find_object_with_ntiid(parent_ntiid)
        for part in getattr(parent, 'parts', None) or ():
            if part.ntiid == ntiid:
                return part
        return None
