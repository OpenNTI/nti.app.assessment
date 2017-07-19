#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 36

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.assessment._question_map import _AssessmentItemOOBTree

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites


def _upgrade_unit(unit):
    try:
        container = unit._question_map_assessment_item_container
        if not isinstance(container, _AssessmentItemOOBTree):
            if container:
                new_container = _AssessmentItemOOBTree()
                new_container.__parent__ = unit
                new_container.__name__ = container.__name__
                new_container.createdTime = container.createdTime
                new_container.lastModified = container.lastModified
                new_container.extend(container.values())
                unit._question_map_assessment_item_container = new_container
            else:
                del unit._question_map_assessment_item_container
            # ground & clear
            container.__name__ = None
            container.__parent__ = None
            container.clear()
            # mark changed
            unit._p_changed = True
    except AttributeError:
        pass


def _process_pacakge(package):
    def _recur(unit):
        _upgrade_unit(unit)
        for child in unit.children or ():
            _recur(child)
    _recur(package)


def _process_site(intids, seen):
    for package in yield_sync_content_packages():
        doc_id = intids.queryId(package)
        if doc_id is None or doc_id in seen:
            continue
        seen.add(doc_id)
        _process_pacakge(package)


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


def do_evolve(context, generation=generation):
    logger.info("Assessment evolution %s started", generation)

    setHooks()
    conn = context.connection
    ds_folder = conn.root()['nti.dataserver']
    lsm = ds_folder.getSiteManager()
    intids = lsm.getUtility(IIntIds)

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)

    with current_site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        library = component.queryUtility(IContentPackageLibrary)
        if library is not None:
            library.syncContentPackages()

        seen = set()
        for site in get_all_host_sites():
            with current_site(site):
                _process_site(intids, seen)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done.', generation)


def evolve(context):
    """
    Evolve to generation 36 by updating the assessment item container for content units
    """
    do_evolve(context)
