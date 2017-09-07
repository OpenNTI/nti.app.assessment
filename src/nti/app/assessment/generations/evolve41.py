#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 41

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.location import locate

from zope.intid.interfaces import IIntIds

from nti.app.assessment.index import IX_HAS_FILE
from nti.app.assessment.index import IX_ASSESSMENT_ID
from nti.app.assessment.index import AssesmentHasFileIndex
from nti.app.assessment.index import install_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseSubmissionItem

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver


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

        catalog = install_submission_catalog(ds_folder, intids)
        if not IX_HAS_FILE in catalog:
            index = AssesmentHasFileIndex(intids.family)
            locate(index, catalog, IX_HAS_FILE)
            intids.register(index)
            catalog[IX_HAS_FILE] = index

            source = catalog[IX_ASSESSMENT_ID]
            for doc_id in source.ids():
                obj = intids.queryOject(doc_id)
                if IUsersCourseSubmissionItem.providedBy(obj):
                    index.index_doc(doc_id, obj)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done', generation)


def evolve(context):
    """
    Evolve to generation 41 by installing the hasFile index in the submission catalog
    """
    do_evolve(context)
