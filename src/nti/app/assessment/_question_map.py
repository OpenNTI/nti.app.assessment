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

from zope.component.hooks import getSite

from zope.container.contained import Contained

from zope.container.btree import BTreeContainer

from zope.deprecation import deprecated

from zope.intid.interfaces import IIntIds

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from ZODB.interfaces import IConnection

from BTrees.OOBTree import OOBTree

from persistent.list import PersistentList

from persistent.mapping import PersistentMapping

from nti.app.assessment.common import get_content_packages_assessment_items

from nti.assessment._question_index import QuestionIndex
from nti.assessment._question_index import _ntiid_object_hook
from nti.assessment._question_index import _load_question_map_json

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE

from nti.contentlibrary.indexed_data import get_site_registry

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IContentPackageSyncResults

from nti.contentlibrary.synchronize import ContentPackageSyncResults

from nti.dublincore.time_mixins import PersistentCreatedAndModifiedTimeObject

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.externalization.persistence import NoPickle

from nti.externalization.proxy import removeAllProxies

from nti.intid.common import addIntId
from nti.intid.common import removeIntId

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.publishing.interfaces import IPublishable
from nti.publishing.interfaces import INoPublishLink
from nti.publishing.interfaces import IObjectPublishedEvent

from nti.recorder.interfaces import IRecordable

from nti.recorder.record import copy_transaction_history
from nti.recorder.record import remove_transaction_history

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.wref.interfaces import IWeakRef

NTIID = StandardExternalFields.NTIID

deprecated('_AssessmentItemContainer', 'Replaced with a persistent mapping')
class _AssessmentItemContainer(PersistentList):
	pass

deprecated('_AssessmentItemStore', 'Deprecated Storage Mode')
class _AssessmentItemStore(BTreeContainer):
	pass

deprecated('_AssessmentItemBucket', 'Deprecated Storage Mode')
class _AssessmentItemBucket(PersistentMapping,
							PersistentCreatedAndModifiedTimeObject,
							Contained):
	assessments = PersistentMapping.values


@component.adapter(IContentUnit)
@interface.implementer(IQAssessmentItemContainer)
class _AssessmentItemOOBTree(OOBTree,
							 PersistentCreatedAndModifiedTimeObject, 
							 Contained):
	
	_SET_CREATED_MODTIME_ON_INIT = False
	
	def __init__(self, *args, **kwargs):
		OOBTree.__init__(self)
		PersistentCreatedAndModifiedTimeObject.__init__(self, *args, **kwargs)
	
	def append(self, item):
		self[item.ntiid] = item
	
	def extend(self, items):
		for item in items or ():
			self.append(item)
	
	def assessments(self):
		return list(self.values())


@component.adapter(IContentUnit)
@interface.implementer(IQAssessmentItemContainer)
def ContentUnitAssessmentItems(unit):
	# Instead of using annotations on the content objects, we
	# use an atttibute since we are seing connection problems
	# during unit tests
	try:
		result = unit._question_map_assessment_item_container
	except AttributeError:
		result = unit._question_map_assessment_item_container = _AssessmentItemOOBTree()
		result.createdTime = time.time()
		result.lastModified = -1
	# make sure there is lineage
	if result.__parent__ is None:
		result.__parent__ = unit
		result.__name__ = '_question_map_assessment_item_container'
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

def _get_assess_item_dict(base):
	"""
	Make sure we iterate through our assessment dict in a
	deterministic order. This ensures everything is registered
	the same way (including the correct containers) every time.
	"""
	def _get_mime( obj ):
		# Except either an assessment object here
		# or an incoming assessment dict.
		try:
			result = obj.mime_type
		except AttributeError:
			result = obj.get( 'MimeType' )
		return result

	result = OrderedDict()
	for mime_type in (ASSIGNMENT_MIME_TYPE,
					  SURVEY_MIME_TYPE,
					  QUESTION_SET_MIME_TYPE,
					  None):
		for key, item in base.items():
			if key in result:
				continue
			elif mime_type == None:
				# Everything else
				result[key] = item
			elif _get_mime( item ) == mime_type:
				result[key] = item
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
		if not IWeakRef.providedBy(component):  # no weak refs
			registerUtility(registry,
							component,
							provided=provided,
							name=name,
							event=event)
			logger.debug("(%s,%s) has been registered", provided.__name__, name)

	def _get_registry(self, registry=None):
		return get_site_registry(registry)

	def _register_and_canonicalize(self, things_to_register, registry=None):
		registry = self._get_registry(registry)
		result = QuestionIndex._register_and_canonicalize(self,
														  things_to_register,
														  registry)
		return result

	def _publish_object(self, item):
		if IPublishable.providedBy(item) and not item.is_published():
			item.publish( event=False )  # by default
			interface.alsoProvides(item, INoPublishLink)

	def _connection(self, registry=None):
		registry = self._get_registry(registry)
		if registry == component.getGlobalSiteManager():
			return None
		else:
			result = IConnection(registry, None)
			return result

	def _intid_register(self, item, registry=None, intids=None, connection=None):
		# We always want to register and persist our assessment items,
		# even from the global library.
		registry = self._get_registry(registry)
		intids = component.queryUtility(IIntIds) if intids is None else intids
		connection = self._connection(registry) if connection is None else connection
		if connection is not None:  # Tests/
			if IConnection(item, None) is None:
				connection.add(item)
			if intids is not None and intids.queryId(item) is None:
				addIntId(item)
			return True
		return False

	def _process_assessments(self,
							 assessment_item_dict,
							 containing_hierarchy_key,
							 content_package,
							 by_file,
							 level_ntiid=None,
							 signatures_dict=None,
							 registry=None,
							 sync_results=None,
							 key_lastModified=None):
		"""
		Returns a set of object that should be placed in the registry, and then
		canonicalized.
		"""

		parent = None
		signatures_dict = signatures_dict or {}
		intids = component.queryUtility(IIntIds)
		library = component.queryUtility(IContentPackageLibrary)
		parents_questions = IQAssessmentItemContainer(content_package)

		# XXX: remove
		hierarchy_ntiids = set()
		hierarchy_ntiids.add(content_package.ntiid)

		if level_ntiid and library is not None:
			containing_content_units = library.pathToNTIID(level_ntiid)
			if containing_content_units:
				parent = containing_content_units[-1]
				parents_questions = IQAssessmentItemContainer(parent)
				hierarchy_ntiids.update((x.ntiid for x in containing_content_units))

		result = set()
		registry = self._get_registry(registry)
		key_lastModified = key_lastModified or time.time()

		assess_dict = _get_assess_item_dict(assessment_item_dict)
		for ntiid, v in assess_dict.items():
			__traceback_info__ = ntiid, v

			factory = find_factory_for(v)
			assert factory is not None

			obj = factory()
			provided = iface_of_assessment(obj)
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
					# get unproxied object
					thing_to_register = removeAllProxies(item)
					thing_to_register.createdTime = thing_to_register.lastModified = key_lastModified

					# check registry
					ntiid = thing_to_register.ntiid
					provided = iface_of_assessment(thing_to_register)
					if ntiid and registry.queryUtility(provided, name=ntiid) is None:
						result.add(thing_to_register)

						# register assesment
						self._registry_utility(registry,
											   component=thing_to_register,
											   provided=provided,
											   name=ntiid)

						# TODO: We are only partially supporting having question/sets
						# used multiple places. When we get to that point, we need to
						# handle it by noting on each assessment object where it is
						# registered
						if thing_to_register.__parent__ is None and parent is not None:
							thing_to_register.__parent__ = parent
						else:
							logger.warn("Could not set parent for %s. %s %s", ntiid,
										thing_to_register.__parent__, parent)

						# publish item
						self._publish_object(thing_to_register)

						# add to container and get and intid
						self._intid_register(thing_to_register,
											 intids=intids,
											 registry=registry)
						parents_questions.append(thing_to_register)

						# register in sync results
						if sync_results is not None:
							sync_results.add_assessment(thing_to_register, False)
					elif ntiid and ntiid not in parents_questions:
						# Child item locked/edited.
						# Update parent and put in parent container.
						parents_questions.append(thing_to_register)
						thing_to_register.__parent__ = parent
			else:
				# These are locked/edited objects. We want to
				# make sure we place in parent container and make sure
				# we update lineage to the new content unit objects.
				obj = registered
				obj.__parent__ = parent
				self._store_object(ntiid, obj)
				things_to_register = self._explode_object_to_register(obj)
				for item in things_to_register:
					item = removeAllProxies(item)
					item.__parent__ = parent
				if ntiid not in parents_questions:
					parents_questions.append(registered)

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
						  sync_results=None,
						  key_lastModified=None):
		"""
		Called with an entry for a file or (sub)section. May or may not have
		children of its own.

		Returns a set of things to register and canonicalize.

		"""
		key_for_this_level = nearest_containing_key
		index_key = index.get('filename')
		if index_key:
			factory = list
			key_for_this_level = content_package.make_sibling_key(index_key)
			if key_for_this_level in by_file:
				# Across all indexes, every filename key should be unique.
				# We rely on this property when we lookup the objects to return
				# We make an exception for index.html, due to a duplicate bug in
				# old versions of the exporter, but we ensure we can't put any questions on it
				if index_key == 'index.html':
					logger.warn("Duplicate 'index.html' entry in %s; update content",
								content_package)
				else:
					__traceback_info__ = index_key, key_for_this_level
					logger.warn("Second entry for the same file %s,%s",
								index_key, key_for_this_level)

			by_file[key_for_this_level] = factory()

		things_to_register = set()
		key_lastModified = key_lastModified or time.time()
		level_ntiid = index.get(NTIID) or nearest_containing_ntiid
		items = self._process_assessments(index.get("AssessmentItems", {}),
									 	  key_for_this_level,
									  	  content_package,
									  	  by_file,
									  	  level_ntiid,
									 	  index.get("Signatures"),
									 	  registry=registry,
									 	  sync_results=sync_results,
									 	  key_lastModified=key_lastModified)
		things_to_register.update(items)

		for child_item in index.get('Items', {}).values():
			items = self._from_index_entry(child_item,
									 	   content_package,
									   	   by_file,
									   	   nearest_containing_key=key_for_this_level,
									   	   nearest_containing_ntiid=level_ntiid,
									   	   registry=registry,
									   	   sync_results=sync_results,
									   	   key_lastModified=key_lastModified)
			things_to_register.update(items)

		return things_to_register

	def _from_root_index(self,
						 assessment_index_json,
						 content_package,
						 registry=None,
						 sync_results=None,
						 key_lastModified=None):
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
		key_lastModified = key_lastModified or time.time()

		# 7.2017 We used to validate we did not have items directly in the root_ntiid.
		# That should no longer be a concern.
		by_file = self._get_by_file()

		things_to_register = set()
		if sync_results is None:
			sync_results = _new_sync_results(content_package)

		for child_ntiid, child_index in root_items.items():
			__traceback_info__ = child_ntiid, child_index, content_package
			# Each of these should have a filename. If they do not, they obviously
			# cannot contain  assessment items. The condition of a missing/bad filename
			# has been seen in jacked-up content that abuses the section hierarchy
			# (skips levels) and/or jacked-up themes/configurations  that split incorrectly.
			# 6.2017 - this constraint may no longer be necessary; so let's just warn.
			if 	   'filename' not in child_index \
				or not child_index['filename'] \
				or child_index['filename'].startswith('index.html#'):
				logger.warn("Invalid child with invalid filename '%s'; cannot contain assessments: %s",
							child_index.get('filename', ''),
							child_index)

			parsed = self._from_index_entry(child_index,
									   		content_package,
									   		by_file,
									   		registry=registry,
									   		sync_results=sync_results,
									   		key_lastModified=key_lastModified,
									   		nearest_containing_ntiid=child_ntiid,)
			things_to_register.update(parsed)

		# register assessment items
		registered = self._register_and_canonicalize(things_to_register, registry)

		# For tests and such, sort
		for questions in by_file.values():
			questions.sort(key=lambda q: q.__name__)

		registered = {x.ntiid for x in registered}
		return by_file, registered

def populate_question_map_json(asm_index_json,
							   content_package,
							   registry=None,
							   sync_results=None,
							   question_map=None,
							   key_lastModified=None):
	result = None
	if asm_index_json:
		if sync_results is None:
			sync_results = _new_sync_results(content_package)

		question_map = QuestionMap() if question_map is None else question_map
		result = question_map._from_root_index(asm_index_json,
											   content_package,
											   registry=registry,
											   sync_results=sync_results,
											   key_lastModified=key_lastModified)
		result = None if result is None else result[1]  # registered
	return result or set()

def _populate_question_map_from_text(question_map,
									 asm_index_text,
									 content_package,
									 registry=None,
									 sync_results=None,
									 key_lastModified=None):
	index = _load_question_map_json(asm_index_text)
	return populate_question_map_json(asm_index_json=index,
									  registry=registry,
									  question_map=question_map,
									  sync_results=sync_results,
									  content_package=content_package,
									  key_lastModified=key_lastModified)

def _add_assessment_items_from_new_content(content_package, key=None, sync_results=None):
	if sync_results is None:
		sync_results = _new_sync_results(content_package)

	if key is None:
		key = content_package.does_sibling_entry_exist('assessment_index.json')
	key_lastModified = key.lastModified if key is not None else None

	question_map = QuestionMap()
	asm_index_text = key.readContentsAsText()
	result = _populate_question_map_from_text(question_map,
											  asm_index_text,
											  content_package,
											  sync_results=sync_results,
											  key_lastModified=key_lastModified)

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
	return key

@component.adapter(IContentPackage, IObjectAddedEvent)
def add_assessment_items_from_new_content(content_package, event, key=None):
	"""
	Assessment items have their NTIID as their __name__, and the NTIID of their primary
	container within this context as their __parent__ (that should really be the hierarchy entry)
	"""
	result = None
	key = key or _needs_load_or_update(content_package)  # let other callers give us the key
	if key is not None:
		logger.info("Reading/Adding assessment items from new content %s %s %s",
					content_package, key, event)
		sync_results = _get_sync_results(content_package, event)
		result = _add_assessment_items_from_new_content(content_package,
														key,
														sync_results=sync_results)
		# mark last modified
		IQAssessmentItemContainer(content_package).lastModified = key.lastModified

	return result or set()

def _remove_assessment_items_from_oldcontent(package, force=False, sync_results=None):
	if sync_results is None:
		sync_results = _new_sync_results(package)

	# Unregister the things from the component registry.
	# We SHOULD be run in the registry where the library item was initially
	# loaded. (We use the context argument to check)
	# FIXME: This doesn't properly handle the case of
	# having references in different content units; we approximate
	sm = component.getSiteManager()
	if component.getSiteManager(package) is not sm:
		# This could be an assertion
		logger.warn("Removing assessment items from wrong site %s should be %s; may not work",
					sm, component.getSiteManager(package))

	result = dict()
	intids = component.queryUtility(IIntIds)  # test mode

	def _remove(container, name, item):
		if name not in result:
			result[name] = item
			provided = iface_of_assessment(item)
			# unregister utility
			if not unregisterUtility(sm, provided=provided, name=name):
				logger.warn("Could not unregister %s from %s", name, sm)
			else:
				logger.debug("(%s,%s) has been unregistered", provided.__name__, name)
			# unregister from intid
			if intids is not None and intids.queryId(item) is not None:
				removeIntId(item)
		# always remove from container
		container.pop(name, None)

	def _unregister(unit, ntiids_to_ignore):
		unit_items = IQAssessmentItemContainer(unit)
		items = _get_assess_item_dict( unit_items )
		for name, item in items.items():
			if name not in ntiids_to_ignore:
				_remove(unit_items, name, item)
		# reset dates
		unit_items.lastModified = unit_items.createdTime = -1

		for child in unit.children or ():
			_unregister(child, ntiids_to_ignore)

	def _gather_to_ignore(unit, to_ignore_accum):
		unit_items = IQAssessmentItemContainer(unit)
		items = _get_assess_item_dict( unit_items )
		for name, item in items.items():
			if not can_be_removed(item, force):
				provided = iface_of_assessment(item)
				logger.warn("Object (%s,%s) is locked cannot be removed during sync",
							provided.__name__, name)
				# XXX: Make sure we add to the ignore list all items that are exploded
				# so they are not processed
				exploded = QuestionMap.explode_object_to_register(item)
				to_ignore_accum.update(x.ntiid for x in exploded or ())
		for child in unit.children or ():
			_gather_to_ignore(child, to_ignore_accum)

	# We make a first pass to gather all things to be ignored, this
	# is to ensure, if for example, a question is in multiple content
	# units (and in a locked assignment), we do not overwrite (register)
	# its state, leaving the item in the assignment stale.
	_ntiids_to_ignore = set()
	_gather_to_ignore(package, _ntiids_to_ignore)
	_unregister(package, _ntiids_to_ignore)

	# register locked
	for ntiid in _ntiids_to_ignore:
		sync_results.add_assessment(ntiid, locked=True)

	return result, _ntiids_to_ignore

@component.adapter(IContentPackage, IObjectRemovedEvent)
def remove_assessment_items_from_oldcontent(package, event=None, force=True):
	sync_results = _get_sync_results(package, event)
	logger.info("Removing assessment items from old content %s %s",
				package, event)
	result, locked_ntiids = _remove_assessment_items_from_oldcontent(package,
													                 force=force,
													                 sync_results=sync_results)

	return set(result.values()), set(locked_ntiids)

@component.adapter(IContentPackage, IObjectPublishedEvent)
def remove_assessment_items_when_unpublished(package, event=None):
	_remove_assessment_items_from_oldcontent(package, force=True)


def _transfer_locked_items_to_content_package(content_package, added_items, locked_ntiids):
	"""
	If we have locked items, but they do not exist in the added items, add
	them to our content package so that it's possible to remove them if
	they are ever unlocked.
	"""
	added_ntiids = set( x.ntiid for x in added_items or () )
	missing_ntiids = set( locked_ntiids ) - set( added_ntiids )
	for ntiid in missing_ntiids:
		# Try to store in its existing content unit container; otherwise
		# fall back to storing on the content package.
		missing_item = find_object_with_ntiid( ntiid )
		item_parent = find_object_with_ntiid( missing_item.containerId )
		logger.info( 'Attempting to remove item from content, but item is locked (%s) (parent=%s)',
					 ntiid, missing_item.containerId )
		if item_parent is None:
			item_parent = content_package
		parents_questions = IQAssessmentItemContainer( item_parent )
		parents_questions.append( missing_item )
		missing_item.__parent__ = item_parent

def _transfer_transaction_records(removed):
	for item in removed:
		provided = iface_of_assessment(item)
		obj = component.queryUtility(provided, name=item.ntiid)
		if obj is not None:
			copy_transaction_history(item, obj)
		remove_transaction_history(item)

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

	removed_items, locked_ntiids = remove_assessment_items_from_oldcontent(original,
																	 	   event,
																	       force=False)
	logger.info("%s assessment item(s) have been removed from content %s",
				len(removed_items), original)

	registered = add_assessment_items_from_new_content(updated, event,
													   key=update_key)
	logger.info("%s assessment item(s) have been registered for content %s",
				len(registered), updated)

	# Transfer locked items (now gone from content) to the new package.
	assesment_items = get_content_packages_assessment_items(updated)

	if locked_ntiids:
		_transfer_locked_items_to_content_package( content_package,
												   assesment_items,
												   locked_ntiids )

	# Transfer records
	_transfer_transaction_records(removed_items)

	if len(assesment_items) < len(registered):
		raise AssertionError(
				"[%s] Item(s) in content package %s are less that in the registry %s" %
				(content_package.ntiid, len(assesment_items), len(registered)))
