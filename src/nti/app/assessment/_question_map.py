#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementation of the assessment question map and supporting
functions to maintain it.

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import simplejson

from zope import interface
from zope import component
from zope.annotation import factory as an_factory
from zope.lifecycleevent.interfaces import IObjectAddedEvent, IObjectRemovedEvent

from nti.assessment import interfaces as asm_interfaces
from nti.contentfragments import interfaces as cfg_interfaces
from nti.contentlibrary import interfaces as lib_interfaces
from nti.dataserver import interfaces as nti_interfaces

from nti.externalization import internalization
from nti.externalization.persistence import NoPickle

from nti.schema.field import Dict
from nti.schema.field import List
from nti.schema.field import Object

def _ntiid_object_hook( k, v, x ):
	"""
	In this one, rare, case, we are reading things from external
	sources and need to preserve an NTIID value.
	"""
	if 'NTIID' in x and not getattr( v, 'ntiid', None ):
		v.ntiid = x['NTIID']
		v.__name__ = v.ntiid
	if 'value' in x and 'Class' in x and x['Class'] == 'LatexSymbolicMathSolution' and x['value'] != v.value:
		# We started out with LatexContentFragments when we wrote these,
		# and if we re-convert when we read, we tend to over-escape
		# One thing we do need to do, though, is replace long dashes with standard minus signs
		v.value = cfg_interfaces.LatexContentFragment( x['value'].replace( u'\u2212', '-') )

	return v

@interface.implementer(asm_interfaces.IQAssessmentItemContainer,
					   nti_interfaces.IZContained)
@component.adapter(lib_interfaces.IContentUnit)
@NoPickle
class _AssessmentItemContainer(list): # non persistent
	__name__ = None
	__parent__ = None


ContentUnitAssessmentItems = an_factory(_AssessmentItemContainer)

class IFileQuestionMap(interface.Interface):
	"""
	.. note:: This is going away. Temporarily here for testing.
	"""
	by_file = Dict(key_type=Object(lib_interfaces.IDelimitedHierarchyKey, title="The key of the unit"),
				   value_type=List(title="The questions contained in this file"))


def _iface_to_register(thing_to_register):
	iface = asm_interfaces.IQuestion
	if asm_interfaces.IQuestionSet.providedBy(thing_to_register):
		iface = asm_interfaces.IQuestionSet
	elif asm_interfaces.IQAssignment.providedBy(thing_to_register):
		iface = asm_interfaces.IQAssignment
	return iface

@interface.implementer( IFileQuestionMap )
class QuestionMap(dict):

	def __init__(self):
		super(QuestionMap,self).__init__()
		self.by_file = {} # {ntiid => [question]}

	def clear(self):
		super(QuestionMap, self).clear()
		self.by_file.clear()

	def __process_assessments( self, assessment_item_dict,
							   containing_hierarchy_key,
							   content_package,
							   level_ntiid=None ):
		library = component.queryUtility(lib_interfaces.IContentPackageLibrary)
		parent = None
		parents_questions = []
		if level_ntiid:
			# Older tests may not have a library available.
			containing_content_units = library.pathToNTIID(level_ntiid) if library else None
			if containing_content_units:
				parent = containing_content_units[-1]
				parents_questions = asm_interfaces.IQAssessmentItemContainer(parent)

		for k, v in assessment_item_dict.items():
			__traceback_info__ = k, v
			factory = internalization.find_factory_for( v )
			assert factory is not None
			obj = factory()
			internalization.update_from_external_object(obj, v, require_updater=True, notify=False, object_hook=_ntiid_object_hook )
			obj.ntiid = k
			self[k] = obj


			# We don't want to try to persist these, so register them globally.
			gsm = component.getGlobalSiteManager()
			# No matter if we got an assignment or  question set first or the questions
			# first, register the question objects exactly once. Replace
			# any question children of a question set by the registered
			# object.
			# XXX This is really ugly and can be cleaned up
			things_to_register = [obj]
			if asm_interfaces.IQAssignment.providedBy(obj):
				for part in obj.parts:
					qset = part.question_set
					if gsm.queryUtility(asm_interfaces.IQuestionSet, name=qset.ntiid) is None:
						things_to_register.append(qset)
					for child_question in qset.questions:
						if gsm.queryUtility(asm_interfaces.IQuestion, name=child_question.ntiid) is None:
							things_to_register.append( child_question )

			elif asm_interfaces.IQuestionSet.providedBy(obj):
				for child_question in obj.questions:
					if gsm.queryUtility(asm_interfaces.IQuestion, name=child_question.ntiid) is None:
						things_to_register.append( child_question )

			for thing_to_register in things_to_register:
				iface = _iface_to_register(thing_to_register)
				# Make sure not to overwrite something done earlier at any level
				if gsm.queryUtility( iface, name=thing_to_register.ntiid) is not None:
					continue

				gsm.registerUtility( thing_to_register,
									 provided=iface,
									 name=thing_to_register.ntiid,
									 event=False)
				# TODO: We are only partially supporting having question/sets
				# used multiple places. When we get to that point, we need to
				# handle it by noting on each assessment object where it is registered.
				if thing_to_register.__parent__ is None and parent is not None:
					thing_to_register.__parent__ = parent
				parents_questions.append( thing_to_register )


			# Now canonicalize
			if asm_interfaces.IQAssignment.providedBy(obj):
				for part in obj.parts:
					part.question_set = gsm.getUtility(asm_interfaces.IQuestionSet,name=part.question_set.ntiid)
					part.question_set.questions = [gsm.getUtility(asm_interfaces.IQuestion,name=x.ntiid)
												   for x
												   in part.question_set.questions]
			elif asm_interfaces.IQuestionSet.providedBy(obj):
				obj.questions = [gsm.getUtility(asm_interfaces.IQuestion,name=x.ntiid)
								 for x
								 in obj.questions]

			obj.__name__ = unicode( k ).encode('utf8').decode('utf8')


			if containing_hierarchy_key:
				assert containing_hierarchy_key in self.by_file, "Container for file must already be present"
				self.by_file[containing_hierarchy_key].append( obj )

	def __from_index_entry(self, index, content_package,
						   nearest_containing_key=None,
						   nearest_containing_ntiid=None ):
		"""
		Called with an entry for a file or (sub)section. May or may not have children of its own.

		:class content_package:

		"""
		key_for_this_level = nearest_containing_key
		if index.get( 'filename' ):
			key_for_this_level = content_package.make_sibling_key( index['filename'] )
			factory = list
			if key_for_this_level in self.by_file:
				# Across all indexes, every filename key should be unique.
				# We rely on this property when we lookup the objects to return
				# We make an exception for index.html, due to a duplicate bug in
				# old versions of the exporter, but we ensure we can't put any questions on it
				if index['filename'] == 'index.html':
					factory = tuple
					logger.warning( "Duplicate 'index.html' entry in %s; update content", content_package )
				else: # pragma: no cover
					raise ValueError( key_for_this_level, "Found a second entry for the same file" )

			self.by_file[key_for_this_level] = factory()


		level_ntiid = index.get( 'NTIID' ) or nearest_containing_ntiid
		self.__process_assessments( index.get( "AssessmentItems", {} ),
									key_for_this_level,
									content_package,
									level_ntiid )

		for child_item in index.get('Items',{}).values():
			self.__from_index_entry( child_item, content_package,
									 nearest_containing_key=key_for_this_level,
									 nearest_containing_ntiid=level_ntiid )


	def _from_root_index( self, assessment_index_json, content_package ):
		"""
		The top-level is handled specially: ``index.html`` is never allowed to have
		assessment items.
		"""
		__traceback_info__ = assessment_index_json, content_package

		assert 'Items' in assessment_index_json, "Root must contain 'Items'"
		root_items = assessment_index_json['Items']
		if not root_items:
			logger.debug( "Ignoring assessment index that contains no assessments at any level %s", content_package )
			return

		assert len(root_items) == 1, "Root's 'Items' must only have Root NTIID"
		root_ntiid = assessment_index_json['Items'].keys()[0] # TODO: This ought to come from the content_package. We need to update tests to be sure
		assert 'Items' in assessment_index_json['Items'][root_ntiid], "Root's 'Items' contains the actual section Items"
		for child_ntiid, child_index in assessment_index_json['Items'][root_ntiid]['Items'].items():
			__traceback_info__ = child_ntiid, child_index, content_package
			# Each of these should have a filename. If they do not, they obviously cannot contain
			# assessment items. The condition of a missing/bad filename has been seen in
			# jacked-up content that abuses the section hierarchy (skips levels) and/or jacked-up themes/configurations
			# that split incorrectly.
			if 'filename' not in child_index or not child_index['filename'] or child_index['filename'].startswith( 'index.html#' ):
				logger.debug( "Ignoring invalid child with invalid filename '%s'; cannot contain assessments: %s",
							  child_index.get('filename', ''),
							  child_index )
				continue

			assert child_index.get( 'filename' ), 'Child must contain valid filename to contain assessments'
			self.__from_index_entry( child_index, content_package, nearest_containing_ntiid=child_ntiid )

		# For tests and such, sort
		for questions in self.by_file.values():
			questions.sort( key=lambda q: q.__name__ )

@component.adapter(lib_interfaces.IContentPackage,IObjectAddedEvent)
def add_assessment_items_from_new_content( content_package, event ):
	"""
	Assessment items have their NTIID as their __name__, and the NTIID of their primary
	container within this context as their __parent__ (that should really be the hierarchy entry)
	"""
	question_map = component.queryUtility( IFileQuestionMap )
	if question_map is None: #pragma: no cover
		return

	logger.info("Adding assessment items from new content %s %s", content_package, event)

	asm_index_text = content_package.read_contents_of_sibling_entry( 'assessment_index.json' )
	_populate_question_map_from_text( question_map, asm_index_text, content_package )

# We usually get two or more copies, one at the top-level, one embedded
# in a question set, and possibly in an assignment. Although we get the
# most reuse within a single index, we get some reuse across indexes,
# especially in tests
_fragment_cache = dict()

def _populate_question_map_from_text( question_map, asm_index_text, content_package ):

	### XXX: JAM: There seems to be a path, later, after startup, where we can access the
	# IQAssessmentItemContainer for a content unit that did not appear in the assessment index.
	# If it is done during a transaction that wants to commit (a POST/PUT) the hierarchy
	# of AnnotationUtilities will ensure that the IQAssessmentItemContainer we access is stored
	# in the *persistent* local site utility...but our implementation isn't yet persistent
	# and aborts the commit.
	# The workaround is to be sure that every content unit gets its annotation in the root,
	# whether we need it later on or not.
	# Then we still have to figure out what that path is...the example is on POSTing a note
	# to certain Pages collections.
	def _r(unit):
		asm_interfaces.IQAssessmentItemContainer(unit)
		for c in unit.children:
			_r(c)
	_r(content_package)


	if not asm_index_text:
		return

	asm_index_text = unicode(asm_index_text, 'utf-8') if isinstance(asm_index_text, bytes) else asm_index_text
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

		factory = cfg_interfaces.PlainTextContentFragment
		if '<' in v:
			factory = cfg_interfaces.SanitizedHTMLContentFragment
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

	try:
		question_map._from_root_index( index, content_package )
	except (interface.Invalid, ValueError): # pragma: no cover
		# Because the map is updated in place, depending on where the error
		# was, we might have some data...that's not good, but it's not a show stopper either,
		# since we shouldn't get content like this out of the rendering process
		logger.exception( "Failed to load assessment items, invalid assessment_index for %s", content_package )

@component.adapter(lib_interfaces.IContentPackage, IObjectRemovedEvent)
def remove_assessment_items_from_oldcontent(content_package, event):
	question_map = component.queryUtility( IFileQuestionMap )
	library = component.queryUtility(lib_interfaces.IContentPackageLibrary)
	if question_map is None or library is None:
		return

	logger.info("Removing assessment items from old content %s %s", content_package, event)

	# remvoe pkg ref
	question_map.pop(content_package.ntiid, None)

	# remove byfile
	for unit in library.childrenOfNTIID(content_package.ntiid):
		questions = question_map.by_file.pop(unit.key, ())
		for question in questions:
			ntiid = getattr(question, 'ntiid', u'')
			question_map.pop(ntiid, None) # some tests register manually without updating everything

	# Unregister the things from the component registery.
	# FIXME: This doesn't properly handle the case of
	# having references in different content units.
	gsm = component.getGlobalSiteManager()
	for unit in library.childrenOfNTIID(content_package.ntiid) + [content_package]:
		items = asm_interfaces.IQAssessmentItemContainer(unit)
		for item in items:
			gsm.unregisterUtility( item,
								   provided=_iface_to_register(item),
								   name=item.ntiid )
