#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 39

import six

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from nti.app.assessment.evaluations.utils import register_context

from nti.app.assessment.index import get_evaluation_catalog

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ALL_EVALUATION_MIME_TYPES

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.base._compat import text_

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.dataserver.metadata.index import get_metadata_catalog

from nti.site.interfaces import IHostPolicyFolder

from nti.traversal.traversal import find_interface


def get_data_items(intids):
    catalog = get_metadata_catalog()
    query = {
        'mimeType': {'any_of': ALL_EVALUATION_MIME_TYPES}
    }
    for uid in catalog.apply(query) or ():
        item = intids.queryObject(uid)
        if IQEvaluation.providedBy(item):
            folder = IHostPolicyFolder(item, None)
            yield (folder, item, uid)


def _process_removal(doc_id, item, catalog, intids):
    logger.warn("Unregistering %s/%s", doc_id, item.ntiid)
    try:
        from nti.metadata import queue_removed
        queue_removed(item)
    except ImportError:
        pass
    intids.unregister(item)
    catalog.unindex_doc(doc_id)


def _process_items(intids):
    catalog = get_evaluation_catalog()
    for folder, item, doc_id in get_data_items(intids):
        if folder is None:  # global obj that leaked
            _process_removal(doc_id, item, catalog, intids)
            continue

        if      hasattr(item, 'ntiid') \
            and item.ntiid \
            and not isinstance(item.ntiid, six.text_type):
            item.ntiid = text_(item.ntiid)

        if '__name__' in item.__dict__ and 'ntiid' in item.__dict__:
            del item.__dict__['__name__']
            item._p_changed = True

        if hasattr(item, 'signature'):
            delattr(item, 'signature')

        if not IQEditableEvaluation.providedBy(item):
            continue

        course = find_interface(item, ICourseInstance, strict=False)
        if not ICourseInstance.providedBy(getattr(item, '__home__', None)) and course:
            item.__home__ = course
            lifecycleevent.modified(item)

        with current_site(folder):
            registry = component.getSiteManager()
            provided = iface_of_assessment(item)
            registered = component.queryUtility(provided, item.ntiid)
            if registered is None:
                logger.warn("Registering object %s/%s",
                            doc_id, item.ntiid)
                registered = item
                register_context(item, True, registry)
            else:
                uid = intids.queryId(registered)
                if uid is None:
                    registered = item
                    register_context(item, True, registry)
                    logger.warn("Replacing registration object %s/%s",
                                doc_id, item.ntiid)
                elif doc_id != uid:
                    logger.warn("Removing duplicate object %s/%s",
                                doc_id, item.ntiid)
                    _process_removal(doc_id, item, catalog, intids)
                    lifecycleevent.modified(registered)

            ntiid = registered.ntiid
            evaluations = ICourseEvaluations(course, None)
            if evaluations is not None:
                old = evaluations.get(ntiid, None)
                if old is None:
                    evaluations.save(ntiid, registered, False)
                elif old != registered:
                    logger.warn("Replacing entry for object %s", item.ntiid)
                    evaluations.replace(old, registered, False)
                    old.__parent__ = old.__home__ = None
                    intids.unregister(old)


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
        _process_items(intids)

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done', generation)


def evolve(context):
    """
    Evolve to generation 39 by cleaning registration leaks/duplicates for authored evals
    """
    do_evolve(context)
