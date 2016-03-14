#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import zope.i18nmessageid
MessageFactory = zope.i18nmessageid.MessageFactory(__name__)

from zope import component

from nti.app.assessment.index import ASSESMENT_CATALOG_NAME
from nti.app.assessment.index import SUBMISSION_CATALOG_NAME

from nti.dataserver.interfaces import IMetadataCatalog

def get_submission_catalog():
	return component.queryUtility(IMetadataCatalog, name=SUBMISSION_CATALOG_NAME)
