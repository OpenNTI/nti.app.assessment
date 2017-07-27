#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 32

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQuestionSet

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_all_host_sites

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility


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


def _update_registered_objects(site_registry, seen, site_name):
    for ntiid, evaluation in list(site_registry.getUtilitiesFor(IQEvaluation)):
        if ntiid in seen:
            continue
        seen.add(ntiid)

        implemented_iface = iface_of_assessment(evaluation)
        for provided in (IQuestionBank, IRandomizedQuestionSet, IQuestionSet):
            if implemented_iface != provided:
                registered = site_registry.queryUtility(provided, 
                                                        name=evaluation.ntiid)
                if registered is not None:
                    unregisterUtility(site_registry, provided=provided, 
                                      name=evaluation.ntiid)
                    registerUtility(site_registry, evaluation, 
                                    provided=implemented_iface,
                                    name=evaluation.ntiid, event=False)
                    logger.info('[%s] Re-registering assessment (%s) (new=%s) (old=%s)',
                                site_name, evaluation.ntiid, implemented_iface, provided)


def do_evolve(context, generation=generation):
    logger.info("Assessment evolution %s started", generation)

    setHooks()
    conn = context.connection
    ds_folder = conn.root()['nti.dataserver']

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)

    with current_site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        # Load library
        library = component.queryUtility(IContentPackageLibrary)
        if library is not None:
            library.syncContentPackages()

        seen = set()
        for site in get_all_host_sites():
            with current_site(site):
                site_name = site.__name__
                registry = component.getSiteManager()
                _update_registered_objects(registry, seen, site_name)

        seen.clear()

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done.', generation)


def evolve(context):
    """
    Evolve to generation 32 by making sure assessment items are registered
    correctly (mainly around IRandomizedQuestionSets, which should just
    be registered as IQuestionSets).
    """
    do_evolve(context)
