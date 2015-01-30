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

import six
import time
import simplejson

import BTrees

from zope import interface
from zope import component
from zope.interface.common.sequence import IReadSequence

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from zope.site.interfaces import ILocalSiteManager

from ZODB.loglevels import TRACE

from persistent.list import PersistentList

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentfragments.interfaces import LatexContentFragment
from nti.contentfragments.interfaces import PlainTextContentFragment
from nti.contentfragments.interfaces import SanitizedHTMLContentFragment

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IGlobalContentPackageLibrary

from nti.dataserver.interfaces import IZContained

from nti.dublincore.time_mixins import PersistentCreatedAndModifiedTimeObject

from nti.externalization.persistence import NoPickle
from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from ._utils import iface_of_assessment
from ._utils import get_content_packages_assessments

def _ntiid_object_hook( k, v, x ):
	"""
	In this one, rare, case, we are reading things from external
	sources and need to preserve an NTIID value.
	"""
	if 'NTIID' in x and not getattr( v, 'ntiid', None ):
		v.ntiid = x['NTIID']
		v.__name__ = v.ntiid

	if 'value' in x and 'Class' in x and x['Class'] == 'LatexSymbolicMathSolution' and \
		x['value'] != v.value:
		# We started out with LatexContentFragments when we wrote these,
		# and if we re-convert when we read, we tend to over-escape
		# One thing we do need to do, though, is replace long dashes with standard
		# minus signs
		v.value = LatexContentFragment(x['value'].replace(u'\u2212', '-'))

	return v

@interface.implementer(IQAssessmentItemContainer, IZContained, IReadSequence)
@component.adapter(IContentUnit)
class _AssessmentItemContainer(PersistentList,
							   PersistentCreatedAndModifiedTimeObject):
	__name__ = None
	__parent__ = None
	_SET_CREATED_MODTIME_ON_INIT = False

@interface.implementer(IQAssessmentItemContainer, IZContained)
@component.adapter(IContentUnit)
class _BTreeAssessmentItemContainer(BTrees.OOBTree.BTree, 
									PersistentCreatedAndModifiedTimeObject):
	
	def append(self, x):
		self[x.ntiid] = x
		
	def __iter__(self):
		for x in self.values():
			yield x

# Instead of using annotations on the content objects, because we're
# not entirely convinced that the annotation utility, which is ntiid
# based, works correctly for our cases of having matching ntiids but
# different objects, we directly store an attribute on the object.
@interface.implementer(IQAssessmentItemContainer)
@component.adapter(IContentUnit)
def ContentUnitAssessmentItems(unit):
	try:
		result = unit._question_map_assessment_item_container
		return result
	except AttributeError:
		result = unit._question_map_assessment_item_container = _AssessmentItemContainer()
		result.createdTime = time.time()
		result.__parent__ = unit
		result.__name__ = '_question_map_assessment_item_container'
		# But leave last modified as zero
		return result

_iface_to_register = iface_of_assessment # BWC

def _site_name(registry):
	if ILocalSiteManager.providedBy(registry):
		return registry.__parent__.__name__
	return registry.__name__

class IPathFinder(interface.Interface):
	"""
	internal interface to find the path to a content unit
	"""

	def find(unit, ntiid):
		pass

@interface.implementer(IPathFinder)
class _LibraryPathFinder(object):
	
	def find(self, unit, ntiid):
		library = component.queryUtility(IContentPackageLibrary)
		result = library.pathToNTIID(ntiid) if library else ()
		return result
	
@interface.implementer(IPathFinder)
class _PackagePathFinder(object):
	
	def _finder(self, unit, prop, value ):
		if getattr( unit, prop, None ) == value:
			return [unit]
	
		for child in unit.children:
			childPath = self._finder( child, prop, value )
			if childPath:
				childPath.append( unit )
				return childPath
		return None
	
	# XXX Copied from library.py
	def _pathToPropertyValue(self, unit, prop, value ):
		"""
		A convenience function for returning, in order from the root down,
		the sequence of children required to reach one with a property equal to
		the given value.
		"""
		results = self._finder( unit, prop, value )
		if results:
			results.reverse()
		return results
	
	def find(self, unit, ntiid):
		result = self._pathToPropertyValue( unit, 'ntiid', ntiid )
		return result

def pathToNTIID(unit, ntiid):
	finder = component.getUtility(IPathFinder)
	result = finder.find(unit, ntiid)
	return result

@NoPickle
class QuestionMap(object):
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

	def __explode_assignment_to_register(self, assignment):
		things_to_register = set([assignment])
		for part in assignment.parts:
			qset = part.question_set
			things_to_register.update(self.__explode_object_to_register(qset))
		return things_to_register

	def __explode_question_set_to_register(self, question_set):
		things_to_register = set([question_set])
		for child_question in question_set.questions:
			things_to_register.add( child_question )
		return things_to_register

	def __explode_object_to_register(self, obj):
		things_to_register = set([obj])
		if IQAssignment.providedBy(obj):
			things_to_register.update(self.__explode_assignment_to_register(obj))
		elif IQuestionSet.providedBy(obj):
			things_to_register.update(self.__explode_question_set_to_register(obj))
		return things_to_register

	def __canonicalize_question_set(self, obj, registry):
		obj.questions = [registry.getUtility(IQuestion, name=x.ntiid)
						 for x
						 in obj.questions]

	def __canonicalize_object(self, obj, registry):
		if IQAssignment.providedBy(obj):
			for part in obj.parts:
				ntiid = part.question_set.ntiid
				part.question_set = registry.getUtility(IQuestionSet, name=ntiid)
				self.__canonicalize_question_set(part.question_set, registry)
		elif IQuestionSet.providedBy(obj):
			self.__canonicalize_question_set(obj, registry)

	def __register_and_canonicalize(self, things_to_register, registry):

		library = component.queryUtility(IContentPackageLibrary)

		# if we're working in the global library, use the global
		# site manager to not persist; otherwise, use the current site manager
		# so persistence works.
		# NOTE: Because of the way annotations work for content units
		# (being based on a utility that looks to the parent utility first)
		# we must not overlap NTIIDs of questions between parent and children
		# libraries, as we will overwrite the parent
		if registry is None:
			if IGlobalContentPackageLibrary.providedBy(library):
				registry = component.getGlobalSiteManager()
			else:
				registry = component.getSiteManager()

		for thing_to_register in things_to_register:
			iface = _iface_to_register(thing_to_register)
			# Previously, we were very careful not to re-register things
			# that we could find utilities for.
			# This is wrong, because we currently don't support multiple
			# definitions, and everything that we find in this content
			# we do need to register, in this registry.

			# We would like to cut down an churn a bit by checking for
			# equality, but because of the hierarchy that's hard to do
			# (if content exists both in a parent and a child, we'd find
			# the parent, but we really need the registration to be local; this
			# is especially an issue if the parent is global but we're
			# persistent)
			# existing_utility = registry.queryUtility(iface, name=thing_to_register.ntiid)
			# if existing_utility == thing_to_register:
			#	continue

			registry.registerUtility( thing_to_register,
									  provided=iface,
									  name=thing_to_register.ntiid,
									  event=False)

			# a bit of logging
			logger.log(TRACE, "%s registered in %s", thing_to_register.ntiid,
					   _site_name(registry))

		# Now that everything is in place, we can canonicalize
		for o in things_to_register:
			self.__canonicalize_object(o, registry)

	def __process_assessments( self, assessment_item_dict,
							   containing_hierarchy_key,
							   content_package,
							   by_file,
							   level_ntiid=None):
		"""
		Returns a set of object that should be placed in the registry, and then
		canonicalized.

		"""
		parent = None
		parents_questions = []
		if level_ntiid:
			# XXX CS/JZ, 1-29-15: Now that the library is caching paths to ntiid,
			# we're manually traversing our content unit to find our path.  We
			# want to make sure we get our new content units to add assessments to.
			containing_content_units = pathToNTIID( content_package, level_ntiid )
			if containing_content_units:
				parent = containing_content_units[-1]
				parents_questions = IQAssessmentItemContainer(parent)

		result = set()
		for k, v in assessment_item_dict.items():
			__traceback_info__ = k, v
			factory = find_factory_for( v )
			assert factory is not None
			obj = factory()
			update_from_external_object(obj, v, require_updater=True,
										notify=False,
										object_hook=_ntiid_object_hook )
			obj.ntiid = k
			obj.__name__ = unicode( k ).encode('utf8').decode('utf8')
			self._store_object(k, obj)

			# No matter if we got an assignment or question set first or the questions
			# first, register the question objects exactly once. Replace
			# any question children of a question set by the registered
			# object.
			things_to_register = self.__explode_object_to_register(obj)
			result.update(things_to_register)

			for thing_to_register in things_to_register:
				# We don't actually register it here, but we do need
				# to record where it came from.
				# (This is necessary to be sure we can unregister things
				# later)
				parents_questions.append( thing_to_register )

				# TODO: We are only partially supporting having question/sets
				# used multiple places. When we get to that point, we need to
				# handle it by noting on each assessment object where it is registered;
				# XXX: This is probably not a good reference to have, we really
				# want to do these weakly?
				if thing_to_register.__parent__ is None and parent is not None:
					thing_to_register.__parent__ = parent

			if containing_hierarchy_key:
				assert containing_hierarchy_key in by_file, "Container for file must already be present"
				by_file[containing_hierarchy_key].append( obj )

		return result

	def __from_index_entry(self, index, content_package,
						   by_file,
						   nearest_containing_key=None,
						   nearest_containing_ntiid=None):
		"""
		Called with an entry for a file or (sub)section. May or may not have children of its own.

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
					logger.warn("Duplicate 'index.html' entry in %s; update content", content_package )
				else: # pragma: no cover
					logger.warn("Second entry for the same file %s,%s", index_key, key_for_this_level)
					__traceback_info__ = index_key, key_for_this_level
					raise ValueError( key_for_this_level, "Found a second entry for the same file" )

			by_file[key_for_this_level] = factory()

		level_ntiid = index.get( 'NTIID' ) or nearest_containing_ntiid
		things_to_register = set()
		i = self.__process_assessments( index.get( "AssessmentItems", {} ),
										key_for_this_level,
										content_package,
										by_file,
										level_ntiid)

		things_to_register.update(i)
		for child_item in index.get('Items',{}).values():
			i = self.__from_index_entry( child_item, content_package,
										 by_file,
										 nearest_containing_key=key_for_this_level,
										 nearest_containing_ntiid=level_ntiid)

			things_to_register.update(i)

		return things_to_register

	def _from_root_index( self, assessment_index_json, content_package,
						  registry=None):
		"""
		The top-level is handled specially: ``index.html`` is never allowed to have
		assessment items.
		"""
		__traceback_info__ = assessment_index_json, content_package

		assert 'Items' in assessment_index_json, "Root must contain 'Items'"
		root_items = assessment_index_json['Items']
		if not root_items:
			logger.warn("Ignoring assessment index that contains no assessments at any level %s", content_package )
			return

		assert len(root_items) == 1, "Root's 'Items' must only have Root NTIID"
		
		# TODO: This ought to come from the content_package. We need to update tests to be sure
		root_ntiid = assessment_index_json['Items'].keys()[0] 
		
		by_file = self._get_by_file()
		assert 'Items' in assessment_index_json['Items'][root_ntiid], "Root's 'Items' contains the actual section Items"

		things_to_register = set()

		for child_ntiid, child_index in assessment_index_json['Items'][root_ntiid]['Items'].items():
			__traceback_info__ = child_ntiid, child_index, content_package
			# Each of these should have a filename. If they do not, they obviously cannot contain
			# assessment items. The condition of a missing/bad filename has been seen in
			# jacked-up content that abuses the section hierarchy (skips levels) and/or jacked-up themes/configurations
			# that split incorrectly.
			if 'filename' not in child_index or not child_index['filename'] or \
				child_index['filename'].startswith( 'index.html#' ):
				logger.warn( "Ignoring invalid child with invalid filename '%s'; cannot contain assessments: %s",
							  child_index.get('filename', ''),
							  child_index )
				continue

			assert child_index.get( 'filename' ), 'Child must contain valid filename to contain assessments'
			i = self.__from_index_entry( child_index, content_package,
										 by_file,
										 nearest_containing_ntiid=child_ntiid)
			things_to_register.update(i)

		# register assessment items
		self.__register_and_canonicalize(things_to_register, registry)

		# For tests and such, sort
		for questions in by_file.values():
			questions.sort( key=lambda q: q.__name__ )

		registered =  {x.ntiid for x in things_to_register}
		return by_file, registered

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
def add_assessment_items_from_new_content( content_package, event, key=None ):
	"""
	Assessment items have their NTIID as their __name__, and the NTIID of their primary
	container within this context as their __parent__ (that should really be the hierarchy entry)
	"""
	question_map = QuestionMap()
	key = key or _needs_load_or_update(content_package) # let other callers give us the key
	if not key:
		return

	logger.info("Reading/Adding assessment items from new content %s %s %s",
				content_package, key, event)
	asm_index_text = key.readContentsAsText()
	result = _populate_question_map_from_text(question_map, asm_index_text,
											  content_package )

	logger.info("%s assessment item(s) read from %s %s",
				len(result or ()), content_package, key)
	return result

# We usually get two or more copies, one at the top-level, one embedded
# in a question set, and possibly in an assignment. Although we get the
# most reuse within a single index, we get some reuse across indexes,
# especially in tests
_fragment_cache = dict()

def _load_question_map_json(asm_index_text):

	if not asm_index_text:
		return

	asm_index_text = unicode(asm_index_text, 'utf-8') \
					 if isinstance(asm_index_text, bytes) else asm_index_text
	# In this one specific case, we know that these are already
	# content fragments (probably HTML content fragments)
	# If we go through the normal adapter process from string to
	# fragment, we will wind up with sanitized HTML, which is not what
	# we want, in this case
	# TODO: Needs specific test cases
	# NOTE: This breaks certain assumptions that assume that there are no
	# subclasses of str or unicode, notably pyramid.traversal. See assessment_views.py
	# for more details.

	def _as_fragment(v):
		# We also assume that HTML has already been sanitized and can
		# be trusted.
		if v in _fragment_cache:
			return _fragment_cache[v]

		factory = PlainTextContentFragment
		if '<' in v:
			factory = SanitizedHTMLContentFragment
		result = factory(v)
		_fragment_cache[v] = result
		return result

	_PLAIN_KEYS = {'NTIID', 'filename', 'href', 'Class', 'MimeType'}

	def _tx(v, k=None):
		if isinstance(v, list):
			v = [_tx(x, k) for x in v]
		elif isinstance(v, dict):
			v = hook(v.iteritems())
		elif isinstance(v, six.string_types):
			if k not in _PLAIN_KEYS:
				v = _as_fragment(v)
			else:
				if v not in _fragment_cache:
					_fragment_cache[v] = v
				v = _fragment_cache[v]

		return v

	def hook(o):
		result = dict()
		for k, v in o:
			result[k] = _tx(v, k)
		return result

	index = simplejson.loads( asm_index_text,
							  object_pairs_hook=hook )
	return index

def _populate_question_map_from_text( question_map, asm_index_text, content_package ):
	index = _load_question_map_json(asm_index_text)
	if not index:
		return

	try:
		result = question_map._from_root_index( index, content_package )
		return set() if result is None else result[1] # registered
	except (interface.Invalid, ValueError): # pragma: no cover
		# Because the map is updated in place, depending on where the error
		# was, we might have some data...that's not good, but it's not a show stopper either,
		# since we shouldn't get content like this out of the rendering process
		logger.exception( "Failed to load assessment items, invalid assessment_index for %s", content_package )

@component.adapter(IContentPackage, IObjectRemovedEvent)
def remove_assessment_items_from_oldcontent(content_package, event):
	logger.info("Removing assessment items from old content %s %s", content_package, event)

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

	result = set()
	def _unregister(unit):
		items = IQAssessmentItemContainer(unit)
		for item in items or ():
			# TODO: Check the parent? If it's an IContentUnit, only
			# unregister if it's us?
			sm.unregisterUtility( item,
								  provided=_iface_to_register(item),
								  name=item.ntiid )
			result.add(item.ntiid)

			# a bit of logging
			logger.log(TRACE, "%s unregistered from %s", item.ntiid, _site_name(sm))

		# clear out the items, since they are persistent
		del items[:]

		# reset the timestamps
		items.lastModified = items.createdTime = -1

		for child in unit.children:
			_unregister(child)

	_unregister(content_package)
	return result

@component.adapter(IContentPackage, IObjectModifiedEvent)
def update_assessment_items_when_modified(content_package, event):
	# The event may be an IContentPackageReplacedEvent, a subtype of the
	# modification event. In that case, because we are directly storing
	# some information on the instance object, we need to remove
	# from the OLD objects, and store on the NEW objects.
	# Because instance storage, we MUST always load things from the new packages;
	# it would be better to simply copy the assignment objects over and change
	# their parents (less DB churn) but its safer to do it the bulk-force way
	original = getattr(event, 'original', content_package)
	updated = content_package

	logger.info("Updating assessment items from modified content %s %s",
				content_package, event)

	removed = remove_assessment_items_from_oldcontent(original, event)
	registered = add_assessment_items_from_new_content(updated, event)

	logger.info("%s assessment item(s) have been registered for content %s",
				len(registered), content_package)

	assesments = get_content_packages_assessments(updated)
	if len(assesments) < len(registered):
		raise AssertionError("Items in content package are less that in the [site] registry")

	items_added = list(registered.difference(removed))
	if items_added:
		logger.debug("%s added from %s ", items_added, content_package)

	items_removed = list(removed.difference(registered))
	if items_removed:
		logger.debug("%s removed from %s ", items_removed, content_package)
