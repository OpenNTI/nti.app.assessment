#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import defaultdict

from zope import component

from zope.component.hooks import site as current_site

from zope.interface.adapter import _lookupAll as zopeLookupAll  # Private func

from zope.intid.interfaces import IIntIds

from ZODB.interfaces import IConnection

from nti.app.contentlibrary.utils import yield_sync_content_packages

from nti.app.assessment import get_evaluation_catalog

from nti.assessment import EVALUATION_INTERFACES

from nti.assessment._question_index import QuestionIndex

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ALL_EVALUATION_MIME_TYPES

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contentlibrary.interfaces import IContentUnit

from nti.intid.common import addIntId
from nti.intid.common import removeIntId

from nti.metadata import dataserver_metadata_catalog

from nti.site.hostpolicy import get_all_host_sites

from nti.site.interfaces import IHostPolicyFolder

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

def lookup_all_evaluations(site_registry):
	result = {}
	required = ()
	order = len(required)
	for registry in site_registry.utilities.ro:  # must keep order
		byorder = registry._adapters
		if order >= len(byorder):
			continue
		components = byorder[order]
		extendors = EVALUATION_INTERFACES
		zopeLookupAll(components, required, extendors, result, 0, order)
		break  # break on first
	return result

def _master_data_collector():
	seen = set()
	registered = {}
	containers = defaultdict(list)
	legacy = {ntiid for ntiid, _ in list(component.getUtilitiesFor(IQEvaluation))}

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
		for ntiid, item in lookup_all_evaluations(registry).items():
			key = (ntiid, site.__name__)
			if key not in registered and ntiid not in legacy:
				registered[key] = (site, item)

		with current_site(site):
			for package in yield_sync_content_packages():
				if package.ntiid not in seen:
					seen.add(package.ntiid)
					recur(site, package)

	return registered, containers, legacy

def _get_data_item_counts(intids):
	count = defaultdict(list)
	catalog = dataserver_metadata_catalog()
	query = {
		'mimeType': {'any_of': ALL_EVALUATION_MIME_TYPES}
	}
	for uid in catalog.apply(query) or ():
		item = intids.queryObject(uid)
		if not IQEvaluation.providedBy(item):
			continue
		folder = find_interface(item, IHostPolicyFolder, strict=False)
		name = getattr(folder, '__name__', None)
		key = (item.ntiid, name)
		count[key].append(item)
	return count

def check_assessment_integrity(remove=False):
	intids = component.getUtility(IIntIds)
	count = _get_data_item_counts(intids)
	logger.info('%s item(s) counted', len(count))
	all_registered, all_containers, legacy = _master_data_collector()

	result = 0
	removed = set()
	duplicates = dict()
	catalog = get_library_catalog()
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
			for item in data:
				iid = intids.queryId(item)
				if iid is not None:
					removeIntId(item)
					removed.add(ntiid)
					
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
				item.__parent__ = None
				catalog.unindex(doc_id)
				removeIntId(item)

		# canonicalize
		QuestionIndex.canonicalize_object(registered, registry)

	logger.info('%s record(s) unregistered', result)

	reindexed = set()
	fixed_lineage = set()
	adjusted_container = set()
	catalog = get_evaluation_catalog()

	# check all registered items
	for key, things in all_registered.items():
		ntiid, _ = key
		if ntiid in legacy:
			continue
		site, registered = things
		uid = intids.queryId(registered)
		containers = all_containers.get(key)

		if uid is not None and not catalog.get_containers(registered):
			logger.warn("Reindexing %s", ntiid)
			reindexed.add(ntiid)
			catalog.index_doc(uid, registered)

		if IQEditableEvaluation.providedBy(registered):
			continue

		# fix lineage
		if registered.__parent__ is None:
			if containers:
				unit = find_interface(containers[0], IContentUnit, strict=False)
				if unit is not None:
					logger.warn("Fixing lineage for %s", key)
					fixed_lineage.add(ntiid)
					registered.__parent__ = unit
					if uid is not None:
						catalog.index_doc(uid, registered)
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
