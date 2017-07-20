#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 37

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from zope.location import locate

from nti.app.assessment.index import IX_KEYWORDS
from nti.app.assessment.index import IX_DISCUSSION_NTIID
from nti.app.assessment.index import get_evaluation_catalog
from nti.app.assessment.index import EvaluationDiscussionNTIIDIndex

from nti.assessment.interfaces import IQDiscussionAssignment

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites

IX_OLD_NAME = 'keyworkds'


def _process_site(intids, seen, catalog):
    for obj in component.getUtilitiesFor(IQDiscussionAssignment):
        doc_id = intids.queryId(obj)
        if doc_id is None or doc_id in seen:
            continue
        seen.add(doc_id)
        catalog.index_doc(doc_id, obj)


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

        catalog = get_evaluation_catalog(lsm)

        # install index
        if IX_DISCUSSION_NTIID not in catalog:
            index = EvaluationDiscussionNTIIDIndex(family=intids.family)
            locate(index, catalog, IX_DISCUSSION_NTIID)
            catalog[IX_DISCUSSION_NTIID] = index
            intids.register(index)

        # rename index
        if IX_OLD_NAME in catalog:
            index = catalog[IX_OLD_NAME]
            del catalog[IX_OLD_NAME]
            locate(index, catalog, IX_KEYWORDS)
            catalog[IX_KEYWORDS] = index
            intids.register(index)

        # index discussion evals
        seen = set()
        for site in get_all_host_sites():
            with current_site(site):
                _process_site(intids, seen, catalog)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done. %s object(s) indexed', 
                generation, len(seen))


def evolve(context):
    """
    Evolve to generation 37 by installing the discussion index
    """
    do_evolve(context)
