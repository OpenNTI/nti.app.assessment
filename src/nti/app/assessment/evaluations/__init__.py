#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from nti.app.externalization.error import raise_json_error

def raise_error(v, tb=None, factory=hexc.HTTPUnprocessableEntity):
	request = get_current_request()
	raise_json_error(request, factory, v, tb)

import zope.deferredimport
zope.deferredimport.initialize()

zope.deferredimport.deprecatedFrom(
	"Moved to nti.app.assessment.evaluations.model",
	"nti.app.assessment.evaluations.model",
	"CourseEvaluations"
)
