#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import re

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from nti.app.externalization.error import raise_json_error

logger = __import__('logging').getLogger(__name__)


def raise_error(v, tb=None, factory=hexc.HTTPUnprocessableEntity, request=None):
    request = request or get_current_request()
    raise_json_error(request, factory, v, tb)


def reference_directive_pattern(directive_name):
    """
    Create a pattern matching a line containing a reStructuredText
    directive with the provided name and an ntiid reference,
    e.g. ".. napollref:: <ntiid>"
    """
    pattern = r'\.\.[ ]+%s\s?::\s?(.+)' % directive_name
    return re.compile(pattern, re.VERBOSE | re.UNICODE)

# DO NO REMOVE this deferred import

import zope.deferredimport
zope.deferredimport.initialize()

zope.deferredimport.deprecatedFrom(
    "Moved to nti.app.assessment.evaluations.model",
    "nti.app.assessment.evaluations.model",
    "CourseEvaluations"
)
