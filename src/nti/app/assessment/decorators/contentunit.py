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

from zope.cachedescriptors.property import Lazy

from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

@component.adapter(IEditableContentPackage)
@interface.implementer(IExternalMappingDecorator)
class _PackageEditorLinksDecorator(_AbstractTraversableLinkDecorator):

    @Lazy
    def _acl_decoration(self):
        return getattr(self.request, 'acl_decoration', True)

    def _predicate(self, context, result):
        return (	 super(_PackageEditorLinksDecorator, self)._predicate(context, result)
                 and self._acl_decoration
                 and has_permission(ACT_CONTENT_EDIT, context, self.request))

    def _do_decorate_external(self, context, result_map):
        links = result_map.setdefault(LINKS, [])
        links.append(Link(context,
                          rel='PackageEvaluations',
                          elements=('Evaluations',)))
