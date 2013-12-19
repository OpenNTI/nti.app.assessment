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
from nti.utils import schema

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
class _AssessmentItemContainer(list): # non persistent
	__name__ = None
	__parent__ = None

	def __reduce__(self):
		raise TypeError()

ContentUnitAssessmentItems = an_factory(_AssessmentItemContainer)

class IFileQuestionMap(interface.Interface):
	"""
	.. note:: This is going away. Temporarily here for testing.
	"""
	by_file = schema.Dict( key_type=schema.Object( lib_interfaces.IDelimitedHierarchyKey, title="The key of the unit" ),
						   value_type=schema.List( title="The questions contained in this file" ) )


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
			# Older tests may not have a library available
			containing_content_units = library.pathToNTIID(level_ntiid) if library else None
			if containing_content_units:
				parent = containing_content_units[-1]
				parents_questions = asm_interfaces.IQAssessmentItemContainer(parent)
			else:
				# For the sake of those old tests, we do the old thing
				# and use the containing NTIID as the parent, safely decoded
				# for pyramid traversal (be sure that the things
				# in the tree are actually, strictly, unicode objects, not subclasses.
				# (The unicode function isnt enough as __unicode__ can override that)
				#
				# This note used to live in assessment_views.py; the part about unicode is
				# still accurate, but in general it is only a concern for the old tests
				# now:
				#
				# The __parent__ of a IQuestion we looked up by NTIID
				# turns out to be the unicode NTIID of the primary
				# container where the question is defined. However,
				# pyramid.traversal takes a shortcut when deciding
				# whether it needs to encode the data or not: it uses
				# `segment.__class__ is unicode` (traversal.py line
				# 608 in 1.3.4) this causes a problem if (a) the
				# context contains non ascii characters and (b) is an
				# instance of the UnicodeContentFragment subclass of
				# unicode: things don't get encoded.
				# contentlibrary._question_map has been altered to
				# ensure that this is unicode. we also assert it here.
				parent = unicode(level_ntiid).encode('utf8').decode('utf8') if level_ntiid else None

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
				# Hack in ACL support. We are piggybacking off of
				# IDelimitedEntry's support in authorization_acl.py
				# FIXME: With proper parents, this is probably no longer needed?
				if hasattr(content_package, 'read_contents_of_sibling_entry'):
					def read_contents_of_sibling_entry( sibling_name ):
						return content_package.read_contents_of_sibling_entry( sibling_name )

					# FIXME: This is so very, very wrong
					# See below.
					obj.filename = containing_hierarchy_key
					obj.read_contents_of_sibling_entry = read_contents_of_sibling_entry

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
				logger.debug( "Ignoring invalid child with invalid filename; cannot contain assessments: %s", child_index )
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

def _populate_question_map_from_text( question_map, asm_index_text, content_package ):
	if not asm_index_text:
		return

	asm_index_text = unicode(asm_index_text, 'utf-8') if isinstance(asm_index_text, six.binary_type) else asm_index_text
	# In this one specific case, we know that these are already
	# content fragments (probably HTML content fragments)
	# If we go through the normal adapter process from string to
	# fragment, we will wind up with sanitized HTML, which is not what
	# we want, in this case
	# TODO: Needs specific test cases
	# NOTE: This breaks certain assumptions that assume that there are no
	# subclasses of str or unicode, notably pyramid.traversal. See assessment_views.py
	# for more details.
	def hook(o):
		return dict( (k,cfg_interfaces.UnicodeContentFragment(v) if isinstance(v, unicode) else v) for k, v in o )

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
			question_map.pop(ntiid)

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


from nti.dataserver.authorization_acl import _AbstractDelimitedHierarchyEntryACLProvider

@component.adapter(asm_interfaces.IQuestion)
@interface.implementer(nti_interfaces.IACLProvider)
class _QuestionACLProvider(_AbstractDelimitedHierarchyEntryACLProvider):
	"""
	Hacky provider of ACLs. See QuestionMap.
	"""

	def __init__( self, question ):
		super(_QuestionACLProvider, self).__init__( question )
		# If this question did not come from a containing file, it
		# won't have the right information associated with it and hence
		# we can get no ACL through the super class.
		# Override that here.
		if not hasattr( question, 'read_contents_of_sibling_entry' ):
			self.__acl__ = ()
