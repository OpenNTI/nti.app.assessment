#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 38

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.assessment.evaluations.adapters import evaluations_for_course

from nti.app.assessment.evaluations.importer import EvaluationsImporterMixin

from nti.app.assessment.evaluations.utils import register_context

from nti.assessment import EVALUATION_INTERFACES

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.intid.common import addIntId
from nti.intid.common import removeIntId

from nti.site.hostpolicy import get_all_host_sites

ORDER = {i: x for i, x in enumerate(EVALUATION_INTERFACES)}.items()


def _get_key(item):
    for i, iface in ORDER:
        if iface.providedBy(item):
            return i
    return 0


def _process_course(context, intids):
    evaluations = evaluations_for_course(context, False)
    if not evaluations:
        return
    importer = EvaluationsImporterMixin()
    for obj in sorted(evaluations.values(), key=_get_key):
        ntiid = obj.ntiid
        provided = iface_of_assessment(obj)
        registered = component.queryUtility(provided, ntiid)
        doc_id = intids.queryId(registered)
        if registered is None or doc_id is None:
            logger.warning("Registering missing object %s", ntiid)
            register_context(obj)
            if doc_id is None:
                addIntId(obj)
            registered = obj
        if obj is not registered:
            logger.warning("Replacing leaked object %s", ntiid)
            evaluations.replace(obj, registered, False)
            removeIntId(obj)
            obj = registered
            lifecycleevent.modified(registered)
        # canonicalize
        if IQuestionSet.providedBy(registered):
            importer.canonicalize_question_set(registered, context)
        elif IQSurvey.providedBy(registered):
            importer.canonicalize_survey(registered, context)
        elif IQAssignment.providedBy(registered):
            importer.canonicalize_assignment(registered, context)

    # fix container length
    evaluations._fix_length()


def _process_site(intids, seen):
    catalog = component.queryUtility(ICourseCatalog)
    if catalog is None or catalog.isEmpty():
        return
    for entry in catalog.iterCatalogEntries():
        course = ICourseInstance(entry)
        doc_id = intids.queryId(course)
        if doc_id is None or doc_id in seen:
            continue
        seen.add(doc_id)
        _process_course(course, intids)


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
    logger.info('Assessment evolution %s done', generation)


def evolve(context):
    """
    Evolve to generation 38 by removing leaks from evaluation containers and
    fix their length
    """
    do_evolve(context)
