#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Weak references for assesments.

.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

logger = __import__('logging').getLogger(__name__)

from zc.intid import IIntIds

from zope import component
from zope import interface

from nti.assessment.interfaces import IQEvaluation

from nti.assessment.wref import ItemWeakRef

from nti.intid.wref import NoCachingArbitraryOrderableWeakRef

from nti.wref.interfaces import IWeakRef


@component.adapter(IQEvaluation)
@interface.implementer(IWeakRef)
def _evaluation_wref(evaluation):
    """
    We prefer intid caching if available, if not, fall back to ntiid weakrefs.
    """
    intids = component.getUtility(IIntIds)
    obj_id = intids.queryId(evaluation)
    if obj_id is not None:
        result = NoCachingArbitraryOrderableWeakRef(evaluation)
    else:
        result = ItemWeakRef(evaluation)
    return result
