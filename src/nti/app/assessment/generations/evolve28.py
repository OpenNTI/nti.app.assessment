#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 27.

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 28

from zope import component
from zope import interface

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from zope.location.location import locate

from nti.app.assessment import get_evaluation_catalog

from nti.app.assessment.index import IX_NTIID
from nti.app.assessment.index import IX_EDITABLE
from nti.app.assessment.index import EvaluationEditableIndex

from nti.assessment.interfaces import IQEvaluation

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

        catalog = get_evaluation_catalog()
        if not IX_EDITABLE in catalog:
            index = EvaluationEditableIndex()
            intids.register(index)
            locate(index, catalog, IX_EDITABLE)
            catalog[IX_EDITABLE] = index

            count = 0
            ntiid_index = catalog[IX_NTIID]
            for doc_id in ntiid_index.ids():
                obj = intids.queryObject(doc_id)
                if IQEvaluation.providedBy(obj):
                    count += 1
                    index.index_doc(doc_id, obj)
            logger.info("%s item(s) processed", count)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done.', generation)


def evolve(context):
    """
    Evolve to generation 28 by registering the editable catalog index
    """
    do_evolve(context)
