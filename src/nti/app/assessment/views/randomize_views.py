#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS

from nti.app.assessment.views.view_mixins import StructuralValidationMixin

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEditableEvaluation

from nti.assessment.randomized.interfaces import IRandomizedQuestionSet
from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.assessment.randomized.question import QRandomizedQuestionSet

from nti.dataserver import authorization as nauth

class AbstractRandomizeView(AbstractAuthenticatedView,
							StructuralValidationMixin):

	#: The message returned for an unacceptable assessment type to modify.
	_TYPE_RANDOMIZE_ERROR_MSG = u''

	#: The message returned for an unacceptable assessment state to modify.
	_STATE_RANDOMIZE_ERROR_MSG = u''

	def _validate(self):
		if not IQEditableEvaluation.providedBy(self.context):
			raise hexc.HTTPUnprocessableEntity(_(self._TYPE_RANDOMIZE_ERROR_MSG))
		self._pre_flight_validation(self.context, structural_change=True)

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 name=VIEW_RANDOMIZE,
			 context=IQuestionSet,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT)
class QuestionSetRandomizeView(AbstractRandomizeView):
	"""
	A view to mark the question set context as containing questions
	in random order.
	"""

	_TYPE_RANDOMIZE_ERROR_MSG = u"Cannot randomize legacy object."

	def __call__(self):
		self._validate()
		interface.alsoProvides(self.context, IRandomizedQuestionSet)
		return self.context

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 name=VIEW_UNRANDOMIZE,
			 context=IQuestionSet,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT)
class QuestionSetUnRandomizeView(AbstractRandomizeView):
	"""
	A view to mark the question set context as containing questions
	not in random order. Concrete QRandomizedQuestionSets cannot
	toggle state.
	"""

	_TYPE_RANDOMIZE_ERROR_MSG = u"Cannot unrandomize legacy object."

	def _validate(self):
		super(QuestionSetUnRandomizeView, self)._validate()
		if isinstance(self.context, QRandomizedQuestionSet):
			# This should not happen.
			raise hexc.HTTPUnprocessableEntity(_("Cannot unrandomize concrete implementation."))

	def __call__(self):
		self._validate()
		if IRandomizedQuestionSet.providedBy(self.context):
			interface.noLongerProvides(self.context, IRandomizedQuestionSet)
		return self.context

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 name=VIEW_RANDOMIZE_PARTS,
			 context=IQuestionSet,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT)
class QuestionSetRandomizePartsView(AbstractRandomizeView):
	"""
	A view to mark the question set context as containing questions
	with randomized parts. This does not change any underlying concrete
	randomized parts. The underlying parts may or may not support
	randomization.
	"""

	_TYPE_RANDOMIZE_ERROR_MSG = u"Cannot randomize parts of legacy object."

	def __call__(self):
		self._validate()
		interface.alsoProvides(self.context, IRandomizedPartsContainer)
		return self.context

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 name=VIEW_UNRANDOMIZE_PARTS,
			 context=IQuestionSet,
			 request_method='POST',
			 permission=nauth.ACT_CONTENT_EDIT)
class QuestionSetUnRandomizePartsView(AbstractRandomizeView):
	"""
	A view to mark the question set context as not containing questions
	with randomized parts. This does not change any underlying concrete
	randomized parts. The underlying parts may or may not support
	randomization.
	"""

	_TYPE_RANDOMIZE_ERROR_MSG = u"Cannot unrandomize parts of legacy object."

	def __call__(self):
		self._validate()
		if IRandomizedPartsContainer.providedBy(self.context):
			interface.noLongerProvides(self.context, IRandomizedPartsContainer)
		return self.context
