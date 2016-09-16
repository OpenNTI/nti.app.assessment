#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_QUESTION_CONTAINERS

from nti.app.assessment.common import get_outline_evaluation_containers

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQuestion

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

@component.adapter(IQuestion)
@interface.implementer(IExternalObjectDecorator)
class QuestionContainerDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Add an `Assessments` link to fetch all assignments and question sets
	containing our given question context and add a `AssessmentContainerCount`.
	"""

	def _predicate(self, context, result):
		return 		self._is_authenticated \
				and has_permission(ACT_CONTENT_EDIT, context, self.request)

	def _do_decorate_external(self, context, result):
		containers = get_outline_evaluation_containers( context )
		result['AssessmentContainerCount'] = len( containers or () )

		_links = result.setdefault(LINKS, [])
		link = Link(context,
					rel=VIEW_QUESTION_CONTAINERS,
					elements=('@@%s' % VIEW_QUESTION_CONTAINERS,))
		interface.alsoProvides(link, ILocation)
		link.__name__ = ''
		link.__parent__ = context
		_links.append(link)
