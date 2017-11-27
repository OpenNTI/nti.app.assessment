#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope.container.contained import Contained

from zope.container.btree import BTreeContainer

from zope.deprecation import deprecated

from persistent.list import PersistentList

from persistent.mapping import PersistentMapping

from nti.dublincore.time_mixins import PersistentCreatedAndModifiedTimeObject

logger = __import__('logging').getLogger(__name__)


deprecated('_AssessmentItemContainer', 'Replaced with a persistent mapping')
class _AssessmentItemContainer(PersistentList):
    pass


deprecated('_AssessmentItemStore', 'Deprecated Storage Mode')
class _AssessmentItemStore(BTreeContainer):
    pass


deprecated('_AssessmentItemBucket', 'Deprecated Storage Mode')
class _AssessmentItemBucket(PersistentMapping,
                            PersistentCreatedAndModifiedTimeObject,
                            Contained):
    assessments = PersistentMapping.values
