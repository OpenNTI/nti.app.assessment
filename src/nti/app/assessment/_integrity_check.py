#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from collections import defaultdict 
from collections import OrderedDict 

from zope import component

from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from ZODB.interfaces import IConnection

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.app.assessment import get_evaluation_catalog

from nti.assessment._question_index import QuestionIndex

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ALL_EVALUATION_MIME_TYPES

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentUnit

from nti.dataserver.metadata.index import get_metadata_catalog

from nti.intid.common import addIntId
from nti.intid.common import removeIntId

from nti.site.hostpolicy import get_all_host_sites

from nti.site.interfaces import IHostPolicyFolder

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


def _master_data_collector(intids):
    seen = set()
    registered = OrderedDict()
    containers = defaultdict(list)
    legacy = component.getGlobalSiteManager().getUtilitiesFor(IQEvaluation)
    legacy = {ntiid for ntiid, _ in list(legacy)}

    def recur(site, unit):
        for child in unit.children or ():
            recur(site, child)
        container = IQAssessmentItemContainer(unit)
        for item in container.assessments():
            ntiid = item.ntiid
            if ntiid not in legacy:
                key = (item.ntiid, site.__name__)
                containers[key].append(container)

    for site in get_all_host_sites():
        registry = site.getSiteManager()
        for ntiid, item in registry.getUtilitiesFor(IQEvaluation):
            if ntiid in legacy:
                continue
            doc_id = intids.queryId(item)
            if doc_id in seen:
                continue
            if doc_id is not None:
                seen.add(doc_id)
            folder = IHostPolicyFolder(item, site)
            key = (ntiid, folder.__name__)
            if key not in registered:
                registered[key] = (folder, item)

        with current_site(site):
            for package in yield_sync_content_packages():
                doc_id = intids.queryId(package)
                if doc_id is None or doc_id in seen:
                    continue
                seen.add(doc_id)
                recur(site, package)

    return registered, containers, legacy


def _get_data_item_counts(intids):
    count = defaultdict(list)
    catalog = get_metadata_catalog()
    query = {
        'mimeType': {'any_of': ALL_EVALUATION_MIME_TYPES}
    }
    for uid in catalog.apply(query) or ():
        item = intids.queryObject(uid)
        if not IQEvaluation.providedBy(item):
            continue
        folder = IHostPolicyFolder(item, None)
        key = (item.ntiid, getattr(folder, '__name__', None))
        count[key].append(item)
    return count


def check_assessment_integrity(remove=False):
    intids = component.getUtility(IIntIds)
    count = _get_data_item_counts(intids)
    logger.info('%s item(s) counted', len(count))
    all_registered, all_containers, legacy = _master_data_collector(intids)

    result = 0
    removed = set()
    duplicates = dict()
    for key, data in count.items():
        ntiid, _ = key
        # find registry and registered objects
        context = data[0]  # pivot
        things = all_registered.get(key)
        provided = iface_of_assessment(context)
        if not things:
            logger.warn("No registration found for %s", key)
            if not remove:
                continue
            # remove from intid facility
            for item in data:
                doc_id = intids.queryId(item)
                if doc_id is not None:
                    removeIntId(item)
                    removed.add(ntiid)
            # remove from containers
            for container in all_containers.get(key) or ():
                container.pop(ntiid, None)
            continue

        if len(data) <= 1 or IQEditableEvaluation.providedBy(context):
            continue
        duplicates[ntiid] = len(data) - 1
        logger.warn("%s has %s duplicate(s)", key, len(data) - 1)

        site, registered = things
        registry = site.getSiteManager()

        # if registered has been found.. check validity
        ruid = intids.queryId(registered)
        if ruid is None:
            logger.warn("Invalid registration for %s", key)
            unregisterUtility(registry, provided=provided, name=ntiid)
            # register a valid object
            registered = context
            ruid = intids.getId(context)
            registerUtility(registry, context, provided, name=ntiid)
            # update map
            all_registered[key] = (site, registered)

        # remove duplicates
        for item in data:
            doc_id = intids.getId(item)
            if doc_id != ruid:
                result += 1
                removeIntId(item)
                item.__home__ = item.__parent__ = None

        # canonicalize
        QuestionIndex.canonicalize_object(registered, registry)

    logger.info('%s record(s) unregistered', result)

    reindexed = set()
    fixed_lineage = set()
    adjusted_container = set()
    catalog = get_evaluation_catalog()
    meta_catalog = get_metadata_catalog()
    
    # check all registered items
    for key, things in all_registered.items():
        ntiid, _ = key
        site, registered = things
        uid = intids.queryId(registered)
        if ntiid in legacy:
            registry = site.getSiteManager()
            if registry is not component.getGlobalSiteManager():
                provided = iface_of_assessment(registered)
                logger.warn("Invalid global registration for %s", key)
                unregisterUtility(registry, provided=provided, name=ntiid)
                if uid is not None:
                    catalog.unindex(uid)
                    removeIntId(registered)
            continue

        containers = all_containers.get(key)
        if uid is not None and not catalog.get_containers(registered):
            logger.warn("Reindexing %s", ntiid)
            reindexed.add(ntiid)
            catalog.index_doc(uid, registered)
            meta_catalog.index_doc(uid, registered)

        registry = site.getSiteManager()
        if      registry is not component.getGlobalSiteManager() \
            and IQAssignment.providedBy(registered):
            for qs in registered.iter_question_sets():
                doc_id = intids.queryId(qs)
                if     doc_id is None \
                    or registry.queryUtility(IQuestionSet, qs.ntiid) is None:
                    logger.warn("Assignment %s/%s has an unregistered question set %s",
                                site.__name__, ntiid, qs.ntiid)
                    
        if IQEditableEvaluation.providedBy(registered):
            continue

        # fix lineage
        if registered.__parent__ is None:
            if containers:
                unit = find_interface(containers[0], 
                                      IContentUnit, 
                                      strict=False)
                if unit is not None:
                    logger.warn("Fixing lineage for %s", key)
                    fixed_lineage.add(ntiid)
                    registered.__parent__ = unit
                    if uid is not None:
                        catalog.index_doc(uid, registered)
                        meta_catalog.index_doc(uid, registered)
            elif remove and uid is not None and not registered.isLocked():
                registry = site.getSiteManager()
                removed.add(ntiid)
                removeIntId(registered)
                provided = iface_of_assessment(registered)
                logger.warn("Removing unparented object %s", key)
                unregisterUtility(registry, provided=provided, name=ntiid)
                continue
        elif uid is None:
            registry = site.getSiteManager()
            connection = IConnection(registry, None)
            if connection is not None:
                if IConnection(registered, None) is None:
                    connection.add(registered)
                addIntId(registered)
                uid = intids.queryId(registered)
                catalog.index_doc(uid, registered)
                meta_catalog.index_doc(uid, registered)

        # make sure containers have registered object
        for container in containers or ():
            item = container.get(ntiid)
            item_iid = intids.queryId(item) if item is not None else None
            if uid is not None and item_iid != uid:
                if item_iid is not None:
                    removeIntId(item)
                logger.warn("Adjusting container for %s", key)
                container.pop(ntiid, None)
                container[ntiid] = registered
                adjusted_container.add(ntiid)

    count_set = set(count.keys())
    reg_set = set(all_registered.keys())
    diff_set = reg_set.difference(count_set)
    for key in sorted(diff_set):
        logger.warn("%s is not registered with metadata catalog", key)

    logger.info('%s registered item(s) checked', len(all_registered))
    return (duplicates, removed, reindexed, fixed_lineage, adjusted_container)
