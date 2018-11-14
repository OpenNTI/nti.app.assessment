#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 27.

.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

generation = 46

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.intid.interfaces import IIntIds

from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.dataserver.metadata.index import get_metadata_catalog

logger = __import__('logging').getLogger(__name__)


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

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)
    intids = lsm.getUtility(IIntIds)

    with site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        total = 0
        metadata_catalog = get_metadata_catalog()
        index = metadata_catalog['mimeType']

        MIME_TYPES = ('application/vnd.nextthought.assessment.userscourseassignmentattemptmetadataitem',)
        item_intids = index.apply({'any_of': MIME_TYPES})
        for doc_id in item_intids or ():
            item = intids.queryObject(doc_id)
            if IUsersCourseAssignmentAttemptMetadataItem.providedBy(item):
                item.__dict__['Seed'] = int(item.Seed)
                item._p_changed = True
                total += 1

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done; %s items(s) updated',
                generation, total)


def evolve(context):
    """
    Evolve to generation 45 by changing the seed fields from str to int.
    """
    do_evolve(context)
