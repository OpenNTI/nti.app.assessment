#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component

from zope.location.interfaces import ILocationInfo

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

class _AbstractTraversableLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, result):
        # We only do this if we can create the traversal path to this object;
        # many times the CourseInstanceEnrollments aren't fully traversable
        # (specifically, for the course roster)
        if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
            if context.__parent__ is None:
                return False # Short circuit
            try:
                loc_info = ILocationInfo( context )
                loc_info.getParents()
            except TypeError:
                return False
            else:
                return True

def _get_course_from_assignment(assignment, user=None, catalog=None, registry=component):
    ## check if we have the context catalog entry we can use 
    ## as reference (.adapters._QProxy) this way
    ## instructor can find the correct course when they are looking
    ## at a section.
    result = None
    try:
        ntiid = assignment.CatalogEntryNTIID
        catalog = catalog if catalog is not None else registry.getUtility(ICourseCatalog)
        try:
            entry = catalog.getCatalogEntry(ntiid) if ntiid else None
            result = ICourseInstance(entry, None)
        except KeyError:
            pass
    except AttributeError:
        pass

    ## could not find a course .. try adapter
    if result is None and user is not None:    
        result = component.queryMultiAdapter((assignment, user), ICourseInstance)
    return result
