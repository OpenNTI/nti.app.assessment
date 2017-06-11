#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from zope import component

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory

from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.ntiids.ntiids import find_object_with_ntiid


def tx_string(s):
    if s and isinstance(s, six.text_type):
        s = s.encode('utf-8')
    return s


def parse_catalog_entry(params, names=('ntiid', 'entry', 'course')):
    ntiid = None
    for name in names:
        ntiid = params.get(name)
        if ntiid:
            break
    if not ntiid:
        return None
    context = find_object_with_ntiid(ntiid)
    result = ICourseCatalogEntry(context, None)
    return result


def get_ds2(request=None):
    request = request if request else get_current_request()
    try:
        result = request.path_info_peek() if request else None
    except AttributeError:  # in unit test we may see this
        result = None
    return result or "dataserver2"
get_path_info = get_ds2
