#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import get_package_from_request

from nti.appserver.interfaces import IEditLinkMaker

from nti.appserver.pyramid_renderers_edit_link_decorator import DefaultEditLinkMaker

from nti.assessment.interfaces import IQEvaluation

from nti.links.links import Link

logger = __import__('logging').getLogger(__name__)


@component.adapter(IQEvaluation)
@interface.implementer(IEditLinkMaker)
class AssesmentEditLinkMaker(DefaultEditLinkMaker):

    def make(self, context, request=None, allow_traversable_paths=True, link_method=None):
        context = self.context if context is None else context
        for composite in (get_course_from_request(request),
                          get_package_from_request(request)):
            if composite is not None:
                link = Link(composite,
                            rel='edit',
                            elements=('Assessments', context.ntiid),
                            method=link_method)
                link.__parent__ = context.__parent__
                link.__name__ = context.__name__
                interface.alsoProvides(link, ILocation)
                return link
        # default
        return DefaultEditLinkMaker.make(self, context, request,
                                         allow_traversable_paths, link_method)
