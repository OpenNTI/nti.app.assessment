#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 40

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.assessment.interfaces import IQEvaluation

from nti.base._compat import text_

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites


def process_site(intids, seen):

    for ntiid, item in component.getUtilitiesFor(IQEvaluation):
        doc_id = intids.queryId(item)
        if doc_id is None or doc_id in seen:
            continue
        seen.add(doc_id)

        if '__name__' in item.__dict__:
            del item.__dict__['__name__']
            item._p_changed = True

        if 'ntiid' not in item.__dict__:
            item.ntiid = text_(ntiid)

        if hasattr(item, 'signature'):
            delattr(item, 'signature')


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
                process_site(intids, seen)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done', generation)


def evolve(context):
    """
    Evolve to generation 40 by removing unused atttributes
    """
    do_evolve(context)
