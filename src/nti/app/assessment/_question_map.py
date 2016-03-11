#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementation of the assessment question map and supporting
functions to maintain it.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time
from collections import OrderedDict

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from zope.component.hooks import getSite

from zope.container.contained import Contained

from zope.deprecation import deprecated

from zope.intid.interfaces import IIntIds

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from ZODB.interfaces import IConnection

from persistent import Persistent

from persistent.mapping import PersistentMapping

from nti.app.assessment.common import get_content_packages_assessment_items

from nti.assessment._question_index import QuestionIndex
from nti.assessment._question_index import _ntiid_object_hook
from nti.assessment._question_index import _load_question_map_json

from nti.assessment.common import iface_of_assessment as _iface_to_register

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE

from nti.common.proxy import removeAllProxies

from nti.containers.containers import NOOwnershipLastModifiedBTreeContainer

from nti.coremetadata.interfaces import IRecordable
from nti.coremetadata.interfaces import IPublishable

from nti.contentlibrary.indexed_data import get_registry
from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IContentPackageSyncResults

from nti.contentlibrary.synchronize import ContentPackageSyncResults

from nti.dublincore.time_mixins import PersistentCreatedAndModifiedTimeObject

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.externalization.persistence import NoPickle

from nti.recorder.record import remove_transaction_history

from nti.site.site import get_component_hierarchy_names

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.wref.interfaces import IWeakRef

deprecated('_AssessmentItemContainer', 'Replaced with a persistent mapping')
class _AssessmentItemContainer(Persistent):
	pass

deprecated('_AssessmentItemBucket', 'Replaced with a container')
class _AssessmentItemBucket(PersistentMapping):
	pass

def has_jar(value):
	try:
		result = value._p_jar is not None  # faster than getattr
	except AttributeError:
		result = False
	return result

@component.adapter(IContentUnit)
@interface.implementer(IQAssessmentItemContainer)
class _AssessmentItemStore(NOOwnershipLastModifiedBTreeContainer,
						   PersistentCreatedAndModifiedTimeObject,
						   Contained):

	_SET_CREATED_MODTIME_ON_INIT = False

	def append(self, item):
		self[item.ntiid] = item

	def extend(self, items):
		for item in items or ():
			self.append(item)

	def assessments(self):
		return list(self.values())
	
	def __setitem__(self, key, value):
		if has_jar(self): 
			# add to jar for unit tests
			if not has_jar(value): 
				self._p_jar.add(value)
			NOOwnershipLastModifiedBTreeContainer.__setitem__(self, key, value)
		else: # global library
			self._setitemf(key, value)
		
	def __delitem__(self, key):
		if has_jar(self):
			NOOwnershipLastModifiedBTreeContainer.__delitem__(self, key)
		else: # global library
			self._delitemf(key, event=False)

@component.adapter(IContentUnit)
@interface.implementer(IQAssessmentItemContainer)
def ContentUnitAssessmentItems(unit):
	annotations = IAnnotations(unit)
	try:
		result = annotations['_question_map_assessment_item_container']
	except KeyError:
		result = _AssessmentItemStore()
		annotations['_question_map_assessment_item_container'] = result
		result.createdTime = time.time()
	return result

def _is_obj_locked(context):
	return IRecordable.providedBy(context) and context.isLocked()

def _can_be_removed(registered, force=False):
	result = registered is not None and (force or not _is_obj_locked(registered))
	return result
can_be_removed = _can_be_removed

def _new_sync_results(content_package):
	result = ContentPackageSyncResults(Site=getattr(getSite(), '__name__', None),
									   ContentPackageNTIID=content_package.ntiid)
	return result

def _get_sync_results(content_package, event):
	all_results = getattr(event, "results", None)
	if not all_results or not IContentPackageSyncResults.providedBy(all_results[-1]):
		result = _new_sync_results(content_package)
		if all_results is not None:
			all_results.append(result)
	elif all_results[-1].ContentPackageNTIID != content_package.ntiid:
		result = _new_sync_results(content_package)
		all_results.append(result)
	else:
		result = all_results[-1]
	return result

@NoPickle
class QuestionMap(QuestionIndex):
	"""
	Originally a single utility that stored all of the assessment items,
	now primarily a place for the algorithm to live, with a bit of bookkeeping
	for tests.

	Other than its event handlers, it must not be used during production code.
	Specifically, one must not rely on being able to reach anything
	from it using its dictionary interface; the global utility WILL NOT
	be in sync with what it available in sub-libraries.
	"""

	def _get_by_file(self):
		# subclasses can override to use persistent storage
		return {}

	def _store_object(self, k, v):
		pass

	def _registry_utility(self, registry, component, provided, name, event=False):
		if not IWeakRef.providedBy(component): # no weak refs
			registerUtility(registry,
							component,
							provided=provided,
							name=name,
							event=event)
			logger.debug("(%s,%s) has been registered", provided.__name__, name)

	def _get_registry(self, registry=None):
		return get_registry(registry)

	def _register_and_canonicalize(self, things_to_register, registry=None):
		registry = self._get_registry(registry)
		result = QuestionIndex._register_and_canonicalize(self,
														  things_to_register,
														  registry)
		return result

	def _index_object(self, assessment_item, content_package,
					  hierarchy_ntiids, registry=None):
		"""
		Index the item in our catalog.
		"""
		result = False
		if IPublishable.providedBy(assessment_item):
			assessment_item.publish() # by default
		if self._get_registry(registry) == component.getGlobalSiteManager():
			return result
		else:
			catalog = get_library_catalog()
			if catalog is not None:  # Test mode
				result = catalog.index(assessment_item, container_ntiids=hierarchy_ntiids,
									   namespace=content_package.ntiid,
									   sites=get_component_hierarchy_names())
		return result

	def _connection(self, registry=None):
		registry = self._get_registry(registry)
		if registry == component.getGlobalSiteManager():
			return None
		else:
			result = IConnection(registry, None)
			return result

	def _lineage(self, resource):
		while resource is not None:
			yield resource
			try:
				resource = resource.__container__
			except AttributeError:
				resource = None

	def _containers(self, resource):
		result = set()
		for x in self._lineage(resource):
			try:
				result.add(x.ntiid)
			except AttributeError:
				pass
		result.discard(None)
		return result

	def _get_assess_item_dict(self, base):
		"""
		Make sure we iterate through our assessment dict in a
		deterministic order. This ensures everything is registered
		the same way (including the correct containers) every time.
		"""
		result = OrderedDict()
		for mime_type in (	ASSIGNMENT_MIME_TYPE,
							SURVEY_MIME_TYPE,
							QUESTION_SET_MIME_TYPE,
							None ):
			for key, assess_dict in base.items():
				if key in result:
					continue
				elif mime_type == None:
					# Everything else
					result[key] = assess_dict
				elif assess_dict.get( 'MimeType' ) == mime_type:
					result[key] = assess_dict
		return result

	def _process_assessments(self,
							 assessment_item_dict,
							 containing_hierarchy_key,
							 content_package,
							 by_file,
							 level_ntiid=None,
							 signatures_dict=None,
							 registry=None,
							 sync_results=None):
		"""
		Returns a set of object that should be placed in the registry, and then
		canonicalized.
		"""

		parent = None
		signatures_dict = signatures_dict or {}
		library = component.queryUtility(IContentPackageLibrary)
		parents_questions = IQAssessmentItemContainer(content_package)

		hierarchy_ntiids = set()
		hierarchy_ntiids.add(content_package.ntiid)

		if level_ntiid and library is not None:
			containing_content_units = library.pathToNTIID(level_ntiid, skip_cache=True)
			if containing_content_units:
				parent = containing_content_units[-1]
				parents_questions = IQAssessmentItemContainer(parent)
				hierarchy_ntiids.update((x.ntiid for x in containing_content_units))

		result = set()
		registry = self._get_registry(registry)

		assess_dict = self._get_assess_item_dict( assessment_item_dict )
		for ntiid, v in assess_dict.items():
			__traceback_info__ = ntiid, v

			factory = find_factory_for(v)
			assert factory is not None

			obj = factory()
			provided = _iface_to_register(obj)
			registered = registry.queryUtility(provided, name=ntiid)
			if registered is None:
				update_from_external_object(obj, v, require_updater=True,
											notify=False,
											object_hook=_ntiid_object_hook)
				obj.ntiid = ntiid
				obj.signature = signatures_dict.get(ntiid)
				obj.__name__ = unicode(ntiid).encode('utf8').decode('utf8')
				self._store_object(ntiid, obj)

				things_to_register = self._explode_object_to_register(obj)

				for item in things_to_register:
					# get containment hierarchy
					containers = self._containers(item)

					# get unproxied object
					thing_to_register = removeAllProxies(item)
					result.add(thing_to_register)

					# check registry
					provided = _iface_to_register(thing_to_register)
					ntiid = getattr(thing_to_register, 'ntiid', None) or u''
					if ntiid and registry.queryUtility(provided, name=ntiid) is None:
						containers.discard(ntiid)
						containers.update(hierarchy_ntiids)

						# register assesment
						self._registry_utility(registry,
											   component=thing_to_register,
											   provided=provided,
											   name=ntiid)

						# TODO: We are only partially supporting having question/sets
						# used multiple places. When we get to that point, we need to
						# handle it by noting on each assessment object where it is registered;
						if thing_to_register.__parent__ is None and parent is not None:
							thing_to_register.__parent__ = parent

						# add to container and get and intid
						parents_questions.append(thing_to_register)

						# index item
						self._index_object(thing_to_register,
										   content_package,
										   containers,
										   registry=registry)

						# register in sync results
						if sync_results is not None:
							sync_results.add_assessment(thing_to_register, False)
			else:
				obj = registered
				self._store_object(ntiid, obj)
				self._index_object(obj,
								   content_package,
								   hierarchy_ntiids,
								   registry=registry)

			if containing_hierarchy_key:
				assert 	containing_hierarchy_key in by_file, \
						"Container for file must already be present"
				by_file[containing_hierarchy_key].append(obj)

		return result

	def _from_index_entry(self,
						  index,
						  content_package,
						  by_file,
						  nearest_containing_key=None,
						  nearest_containing_ntiid=None,
						  registry=None,
						  sync_results=None):
		"""
		Called with an entry for a file or (sub)section. May or may not have
		children of its own.

		Returns a set of things to register and canonicalize.

		"""
		key_for_this_level = nearest_containing_key
		index_key = index.get('filename')
		if index_key:
			key_for_this_level = content_package.make_sibling_key(index_key)
			factory = list
			if key_for_this_level in by_file:
				# Across all indexes, every filename key should be unique.
				# We rely on this property when we lookup the objects to return
				# We make an exception for index.html, due to a duplicate bug in
				# old versions of the exporter, but we ensure we can't put any questions on it
				if index_key == 'index.html':
					factory = tuple
					logger.warn("Duplicate 'index.html' entry in %s; update content",
								content_package)
				else:  # pragma: no cover
					logger.warn("Second entry for the same file %s,%s",
								index_key, key_for_this_level)
					__traceback_info__ = index_key, key_for_this_level
					raise ValueError(key_for_this_level,
									 "Found a second entry for the same file")

			by_file[key_for_this_level] = factory()

		things_to_register = set()
		level_ntiid = index.get('NTIID') or nearest_containing_ntiid
		items = self._process_assessments(index.get("AssessmentItems", {}),
									 	  key_for_this_level,
									  	  content_package,
									  	  by_file,
									  	  level_ntiid,
									 	  index.get("Signatures"),
									 	  registry=registry,
									 	  sync_results=sync_results)
		things_to_register.update(items)

		for child_item in index.get('Items', {}).values():
			items = self._from_index_entry(child_item,
									 	   content_package,
									   	   by_file,
									   	   nearest_containing_key=key_for_this_level,
									   	   nearest_containing_ntiid=level_ntiid,
									   	   registry=registry,
									   	   sync_results=sync_results)
			things_to_register.update(items)

		return things_to_register

	def _from_root_index(self,
						 assessment_index_json,
						 content_package,
						 registry=None,
						 sync_results=None):
		"""
		The top-level is handled specially: ``index.html`` is never allowed to have
		assessment items.
		"""
		__traceback_info__ = assessment_index_json, content_package

		assert 'Items' in assessment_index_json, "Root must contain 'Items'"

		root_items = assessment_index_json['Items']
		if not root_items:
			logger.warn("Ignoring assessment index that contains no assessments at any level %s",
						content_package)
			return
		assert len(root_items) == 1, "Root's 'Items' must only have Root NTIID"

		# TODO: This ought to come from the content_package.
		# We need to update tests to be sure
		root_ntiid = root_items.keys()[0]

		by_file = self._get_by_file()
		assert 	'Items' in root_items[root_ntiid], \
				"Root's 'Items' contains the actual section Items"

		if sync_results is None:
			sync_results = _new_sync_results(content_package)

		things_to_register = set()

		for child_ntiid, child_index in root_items[root_ntiid]['Items'].items():
			__traceback_info__ = child_ntiid, child_index, content_package
			# Each of these should have a filename. If they do not, they obviously
			# cannot contain  assessment items. The condition of a missing/bad filename
			# has been seen in jacked-up content that abuses the section hierarchy
			# (skips levels) and/or jacked-up themes/configurations  that split incorrectly.
			if 'filename' not in child_index or not child_index['filename'] or \
				child_index['filename'].startswith('index.html#'):
				logger.warn("Ignoring invalid child with invalid filename '%s'; cannot contain assessments: %s",
							child_index.get('filename', ''),
							child_index)
				continue

			assert 	child_index.get('filename'), \
					'Child must contain valid filename to contain assessments'

			parsed = self._from_index_entry(child_index,
									   		content_package,
									   		by_file,
									   		nearest_containing_ntiid=child_ntiid,
									   		registry=registry,
									   		sync_results=sync_results)
			things_to_register.update(parsed)

		# register assessment items
		registered = self._register_and_canonicalize(things_to_register, registry)

		# For tests and such, sort
		for questions in by_file.values():
			questions.sort(key=lambda q: q.__name__)

		registered = {x.ntiid for x in registered}
		return by_file, registered

def _populate_question_map_from_text(question_map,
									 asm_index_text,
									 content_package,
									 registry=None,
									 sync_results=None):
	result = None
	index = _load_question_map_json(asm_index_text)
	if index:
		try:
			if sync_results is None:
				sync_results = _new_sync_results(content_package)

			result = question_map._from_root_index(index,
												   content_package,
												   registry=registry,
												   sync_results=sync_results)
			result = None if result is None else result[1]  # registered
		except (interface.Invalid, ValueError):  # pragma: no cover
			# Because the map is updated in place, depending on where the error
			# was, we might have some data...that's not good, but it's not a show stopper
			# either, since we shouldn't get content like this out of the rendering
			# process
			logger.exception(
				"Failed to load assessment items, invalid assessment_index for %s",
				 content_package)
	return result or set()

def _add_assessment_items_from_new_content(content_package, key, sync_results=None):
	if sync_results is None:
		sync_results = _new_sync_results(content_package)

	question_map = QuestionMap()
	asm_index_text = key.readContentsAsText()
	result = _populate_question_map_from_text(question_map,
											  asm_index_text,
											  content_package,
											  sync_results=sync_results)

	logger.info("%s assessment item(s) read from %s %s",
				len(result or ()), content_package, key)
	return result

def _get_last_mod_namespace(content_package):
	return '%s.%s.LastModified' % (content_package.ntiid, 'assessment_index.json')

def _needs_load_or_update(content_package):
	key = content_package.does_sibling_entry_exist('assessment_index.json')
	if not key:
		return

	main_container = IQAssessmentItemContainer(content_package)
	if key.lastModified <= main_container.lastModified:
		logger.info("No change to %s since %s, ignoring",
					key,
					key.modified)
		return
	main_container.lastModified = key.lastModified
	return key

@component.adapter(IContentPackage, IObjectAddedEvent)
def add_assessment_items_from_new_content(content_package, event, key=None):
	"""
	Assessment items have their NTIID as their __name__, and the NTIID of their primary
	container within this context as their __parent__ (that should really be the hierarchy entry)
	"""
	result = None
	key = key or _needs_load_or_update(content_package)  # let other callers give us the key
	if key:
		logger.info("Reading/Adding assessment items from new content %s %s %s",
					content_package, key, event)
		sync_results = _get_sync_results(content_package, event)
		result = _add_assessment_items_from_new_content(content_package,
														key,
														sync_results=sync_results)
	return result or set()

def _remove_assessment_items_from_oldcontent(content_package,
											 force=False,
											 sync_results=None):
	if sync_results is None:
		sync_results = _new_sync_results(content_package)

	# Unregister the things from the component registry.
	# We SHOULD be run in the registry where the library item was initially
	# loaded. (We use the context argument to check)
	# FIXME: This doesn't properly handle the case of
	# having references in different content units; we approximate
	sm = component.getSiteManager()
	if component.getSiteManager(content_package) is not sm:
		# This could be an assertion
		logger.warn("Removing assessment items from wrong site %s should be %s; may not work",
					sm, component.getSiteManager(content_package))

	ignore = set()
	result = dict()
	catalog = get_library_catalog()
	intids = component.queryUtility(IIntIds) # test mode

	def _remove(container, name, item):
		if name not in result:
			result[name] = item
			provided = _iface_to_register(item)
			# unregister
			if not unregisterUtility(sm, provided=provided, name=name):
				logger.warn("Could not unregister %s from %s", name, sm)
			else:
				logger.debug("(%s,%s) has been unregistered", provided.__name__, name)
			# remove from index
			if intids is not None and intids.queryId(item) is not None:
				catalog.unindex(item, intids=intids)
			# remove transactions
			remove_transaction_history(item)
		# always remove from container
		container.pop(name, None)
			
	def _unregister(unit):
		items = IQAssessmentItemContainer(unit)
		for name, item in list(items.items()): # mutating
			if can_be_removed(item, force):
				_remove(items, name, item)
			else:
				provided = _iface_to_register(item)
				logger.warn("Object (%s,%s) is locked cannot be removed during sync",
							provided.__name__, name)
				# XXX: Make sure we add to the ignore list all items that are exploded
				# so they are not processed
				exploded = QuestionMap.explode_object_to_register(item)
				ignore.update(x.ntiid for x in exploded or ())

		# reset dates
		items.lastModified = items.createdTime = -1

		for child in unit.children or ():
			_unregister(child)

	_unregister(content_package)

	# register locked
	for ntiid in ignore:
		sync_results.add_assessment(ntiid, locked=True)

	return result

@component.adapter(IContentPackage, IObjectRemovedEvent)
def remove_assessment_items_from_oldcontent(content_package, event, force=True):
	sync_results = _get_sync_results(content_package, event)
	logger.info("Removing assessment items from old content %s %s", content_package, event)
	result = _remove_assessment_items_from_oldcontent(content_package,
													  force=force,
													  sync_results=sync_results)
	return set(result.keys())

@component.adapter(IContentPackage, IObjectModifiedEvent)
def update_assessment_items_when_modified(content_package, event=None):
	# The event may be an IContentPackageReplacedEvent, a subtype of the
	# modification event. In that case, because we are directly storing
	# some information on the instance object, we need to remove
	# from the OLD objects, and store on the NEW objects.
	# Because instance storage, we MUST always load things from the new packages;
	# it would be better to simply copy the assignment objects over and change
	# their parents (less DB churn) but its safer to do it the bulk-force way
	original = getattr(event, 'original', content_package)
	updated = content_package

	update_key = _needs_load_or_update(updated)
	if not update_key:
		return

	logger.info("Updating assessment items from modified content %s %s",
				content_package, event)

	removed = remove_assessment_items_from_oldcontent(original, event, force=False)
	logger.info("%s assessment item(s) have been removed from content %s",
				len(removed), original)

	registered = add_assessment_items_from_new_content(updated, event, key=update_key)
	logger.info("%s assessment item(s) have been registered for content %s",
				len(registered), updated)

	assesment_items = get_content_packages_assessment_items(updated)
	if len(assesment_items) < len(registered):
		raise AssertionError("[%s] Item(s) in content package %s are less that in the registry %s" %
							(content_package.ntiid, len(assesment_items), len(registered)))
