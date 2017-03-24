#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 29

from collections import Mapping

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from BTrees.OOBTree import OOBTree

from nti.contenttypes.courses.assignment import COURSE_DATE_CONTEXT_KEY
from nti.contenttypes.courses.assignment import COURSE_INSTANCE_DATE_CONTEXT_KEY

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites


@interface.implementer(IDataserver)
class MockDataserver(object):

    root = None

    def get_by_oid(self, oid, ignore_creator=False):
        resolver = component.queryUtility(IOIDResolver)
        if resolver is None:
            logger.warn("Using dataserver without a proper ISiteManager.")
        else:
            return resolver.get_object_by_oid(oid, ignore_creator=ignore_creator)
        return None


def _update_policy(seen, catalog, intids):
    for entry in catalog.iterCatalogEntries():
        course = ICourseInstance(entry, None)
        doc_id = intids.queryId(course)
        if doc_id is None or doc_id in seen:
            continue
        seen.add(course)
        course = ICourseInstance(entry, None)
        annotations = IAnnotations(course, None)
        if not annotations:
            continue
        for name in (COURSE_DATE_CONTEXT_KEY, COURSE_INSTANCE_DATE_CONTEXT_KEY):
            mixin = annotations.get(name)
            if mixin is None:
                continue
            mapping = OOBTree(mixin._mapping)
            for key, value in list(mapping.items()):
                if isinstance(value, Mapping):
                    mapping[key] = OOBTree(value)
            mixin._mapping = mapping
            mixin._p_changed = True


def do_evolve(context, generation=generation):
    conn = context.connection
    ds_folder = conn.root()['nti.dataserver']

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)

    with current_site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        lsm = ds_folder.getSiteManager()
        intids = lsm.getUtility(IIntIds)

        seen = set()
        # global site
        catalog = component.queryUtility(ICourseCatalog)
        _update_policy(seen, catalog, intids)
        # all sites
        for site in get_all_host_sites():
            with current_site(site):
                catalog = component.queryUtility(ICourseCatalog)
                if catalog is not None:
                    _update_policy(seen, catalog, intids)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Evolution %s done.', generation)


def evolve(context):
    """
    Evolve to generation 29 by changing the mapping type in the policies.
    """
    do_evolve(context, generation)
