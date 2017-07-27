#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.site.interfaces import IHostPolicyFolder


def get_resource_site_name(context):
    folder = IHostPolicyFolder(context, None)
    return folder.__name__ if folder is not None else None
get_course_site = get_resource_site_name


def get_resource_site_registry(context):
    folder = IHostPolicyFolder(context, None)
    return folder.getSiteManager() if folder is not None else None
