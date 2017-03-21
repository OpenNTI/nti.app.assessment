#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 34

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from zope.location import locate

from nti.app.assessment.index import IX_CREATOR
from nti.app.assessment.index import CreatorIndex
from nti.app.assessment.index import install_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.metadata import metadata_queue

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

CONTAINER_INTERFACES = (IUsersCourseInquiries,
                        IUsersCourseAssignmentHistories,
                        IUsersCourseAssignmentMetadataContainer)


def add_2_queue(context, queue, intids):
    doc_id = intids.queryId(context)
    if doc_id is not None:
        try:
            queue.add(doc_id)
        except TypeError:
            pass


def process_course(course, queue, intids):
    for provided in CONTAINER_INTERFACES:
        user_data = provided(course, None)
        if not user_data:
            continue
        for item in user_data.values():
            add_2_queue(item, queue, intids)
            try:
                for item in item.values():
                    add_2_queue(item, queue, intids)
            except AttributeError:
                pass


def process_site_courses(seen, queue, intids):
    catalog = component.queryUtility(ICourseCatalog)
    if catalog is None or catalog.isEmpty():
        return
    for entry in catalog.iterCatalogEntries():
        course = ICourseInstance(entry, None)
        doc_id = intids.queryId(course)
        if doc_id is None or doc_id in seen:
            continue
        seen.add(doc_id)
        process_course(course, queue, intids)


def do_evolve(context, generation=generation):
    logger.info("Assessment evolution %s started", generation)

    setHooks()
    conn = context.connection
    ds_folder = conn.root()['nti.dataserver']
    lsm = ds_folder.getSiteManager()

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)

    with current_site(ds_folder):
        assert  component.getSiteManager() == ds_folder.getSiteManager(), \
                "Hooks not installed?"
        intids = lsm.getUtility(IIntIds)
        queue = metadata_queue()
        submission_catalog = install_submission_catalog(ds_folder, intids)
        # recreate creator index
        index = submission_catalog[IX_CREATOR]
        index.clear()  # clear all
        intids.unregister(index)
        del submission_catalog[IX_CREATOR]
        index = CreatorIndex(family=intids.family)
        intids.register(index)
        locate(index, submission_catalog, IX_CREATOR)
        submission_catalog[IX_CREATOR] = index
        # reindex objects
        seen = set()
        for site in get_all_host_sites():
            with current_site(site):
                process_site_courses(seen, queue, intids)
        seen.clear()

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done.', generation)


def evolve(context):
    """
    Evolve to generation 34 by indexing missing submissions
    """
    do_evolve(context)
