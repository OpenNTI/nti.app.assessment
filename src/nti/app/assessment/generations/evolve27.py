#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 27.

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 27

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.catalog.interfaces import ICatalog

from zope.intid.interfaces import IIntIds

from nti.app.assessment.common.assessed import set_assessed_lineage

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.dataserver.metadata.index import CATALOG_NAME as METADATA_CATALOG_NAME


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

    with site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        total = 0
        metadata_catalog = lsm.getUtility(ICatalog, METADATA_CATALOG_NAME)
        index = metadata_catalog['mimeType']

        MIME_TYPES = ('application/vnd.nextthought.assessment.userscourseassignmenthistoryitem',)
        item_intids = index.apply({'any_of': MIME_TYPES})
        for doc_id in item_intids or ():
            item = intids.queryObject(doc_id)
            if IUsersCourseAssignmentHistoryItem.providedBy(item):
                pending = item.pendingAssessment
                if pending is not None:
                    total += 1
                    set_assessed_lineage(pending)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done; %s items(s) indexed',
                generation, total)


def evolve(context):
    """
    Evolve to generation 27 by setting lineage for all Assignment History Item
    """
    do_evolve(context)
