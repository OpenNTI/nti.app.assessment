#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component

from zope.annotation.interfaces import IAnnotations

from zope.component.hooks import getSite

from nti.appserver.policies.interfaces import ISitePolicyUserEventListener

from nti.contenttypes.presentation import NTI

from nti.site.interfaces import IHostPolicyFolder

logger = __import__('logging').getLogger(__name__)


def get_resource_site_name(context):
    folder = IHostPolicyFolder(context, None)
    return folder.__name__ if folder is not None else None
get_course_site = get_resource_site_name


def get_resource_site_registry(context):
    folder = IHostPolicyFolder(context, None)
    return folder.getSiteManager() if folder is not None else None


def get_site_provider():
    policy = component.queryUtility(ISitePolicyUserEventListener)
    result = getattr(policy, 'PROVIDER', None)
    if not result:
        annontations = IAnnotations(getSite(), {})
        result = annontations.get('PROVIDER')
    return result or NTI
