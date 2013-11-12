#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Adapters for application-level events.

$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import component

from nti.appserver import interfaces as app_interfaces
from nti.assessment import interfaces as asm_interfaces
from nti.externalization import interfaces as ext_interfaces

from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.externalization.externalization import to_external_object
from nti.externalization.singleton import SingletonDecorator


@interface.implementer(app_interfaces.INewObjectTransformer)
def _question_submission_transformer( obj ):
	# Grade it, by adapting the object into an IAssessedQuestion
	return asm_interfaces.IQAssessedQuestion

@interface.implementer(app_interfaces.INewObjectTransformer)
def _question_set_submission_transformer( obj ):
	# Grade it, by adapting the object into an IAssessedQuestionSet
	return asm_interfaces.IQAssessedQuestionSet


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
					qs = []

				accum.extend(qs)

				for child in unit.children:
					recur( child, accum )

		result = []
		recur( context.contentUnit, result )

		if result:
			### XXX FIXME: We need to be sure we don't send back the
			# solutions and explanations right now
			result_map['AssessmentItems'] = to_external_object( result  )
