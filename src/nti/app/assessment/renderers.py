#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment.utils import get_course_from_request

from nti.appserver.interfaces import IEditLinkMaker

from nti.appserver.pyramid_renderers_edit_link_decorator import DefaultEditLinkMaker

from nti.assessment.interfaces import IQEvaluation

from nti.links.links import Link


@component.adapter(IQEvaluation)
@interface.implementer(IEditLinkMaker)
class AssesmentEditLinkMaker(DefaultEditLinkMaker):

    def make(self, context, request=None,
             allow_traversable_paths=True, link_method=None):
        context = self.context if context is None else context
        course = get_course_from_request(request)
        if course is not None:
            link = Link(course,
                        rel='edit',
                        elements=('Assessments', context.ntiid),
                        method=link_method)
            link.__parent__ = context.__parent__
            link.__name__ = context.__name__
            interface.alsoProvides(link, ILocation)
            return link
        # default
        return DefaultEditLinkMaker.make(self,
                                         context,
                                         request=request,
                                         link_method=link_method,
                                         allow_traversable_paths=allow_traversable_paths)
