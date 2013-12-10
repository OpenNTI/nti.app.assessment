#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
External object decorators having to do with assessments.

$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.externalization import interfaces as ext_interfaces
from nti.assessment import interfaces as asm_interfaces
from nti.appserver import interfaces as app_interfaces

from nti.externalization.singleton import SingletonDecorator
from nti.externalization.externalization import to_external_object

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
@component.adapter(app_interfaces.IContentUnitInfo)
class _ContentUnitAssessmentItemDecorator(object):
	__metaclass__ = SingletonDecorator

	def decorateExternalMapping( self, context, result_map ):
		if context.contentUnit is None:
			return

		#questions = component.getUtility( app_interfaces.IFileQuestionMap )
		#for_key = questions.by_file.get( getattr( context.contentUnit, 'key', None ) )
		# When we return page info, we return questions
		# for all of the embedded units as well
		def same_file(unit1, unit2):
			try:
				return unit1.filename.split('#',1)[0] == unit2.filename.split('#',1)[0]
			except (AttributeError,IndexError):
				return False

		def recur(unit,accum):
			if same_file( unit, context.contentUnit ):
				try:
					qs = asm_interfaces.IQAssessmentItemContainer( unit, () )
				except TypeError:
					qs = ()

				accum.update( {q.ntiid: q for q in qs} )

				for child in unit.children:
					recur( child, accum )

		result = dict()
		recur( context.contentUnit, result )
		result = list(result.values())

		if result:
			### XXX We need to be sure we don't send back the
			# solutions and explanations right now. This is
			# done in a very hacky way, need something more
			# context sensitive (would the named externalizers
			# work here? like personal-summary for users?)
			### XXX We may not be able to do this yet, the
			# app may be depending on this information. We
			# need to make this available only as part of an assessed
			# value, not in general.
			def _strip(item):
				cls = item.get('Class')
				if cls == 'Question':
					for part in item['parts']:
						part['solutions'] = None
						part['explanation'] = None
				elif cls == 'QuestionSet':
					for q in item['questions']:
						_strip(q)

			ext_items = to_external_object( result )
			#for item in ext_items:
			#	_strip(item)
			result_map['AssessmentItems'] = ext_items

LINKS = ext_interfaces.StandardExternalFields.LINKS
from nti.dataserver.links import Link

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
class _AssignmentHistoryItemDecorator(object):
	"""
	For things that have an assignment history, add this
	as a link.
	"""

	__metaclass__ = SingletonDecorator

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor.

	def decorateExternalMapping( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		links.append( Link( context, rel='AssignmentHistory', elements=('AssignmentHistory',)) )

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
class _AssignmentsByOutlineNodeDecorator(object):
	"""
	For things that have a assignments, add this
	as a link.
	"""

	__metaclass__ = SingletonDecorator

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor.

	def decorateExternalMapping( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		links.append( Link( context, rel='AssignmentsByOutlineNode', elements=('AssignmentsByOutlineNode',)) )
