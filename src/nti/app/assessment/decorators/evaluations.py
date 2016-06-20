#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_COPY_EVALUATION

from nti.app.assessment.decorators import _get_course_from_assignment

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _EvaluationLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		user = self.remoteUser
		course = _get_course_from_assignment(context, user, request=self.request)
		return 		self._is_authenticated \
				and (	has_permission(ACT_CONTENT_EDIT, context, self.request) \
					 or is_course_instructor_or_editor(course, user))

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])
		link = Link(context, rel=VIEW_COPY_EVALUATION,
					elements=(VIEW_COPY_EVALUATION,))
		interface.alsoProvides(link, ILocation)
		link.__name__ = ''
		link.__parent__ = context
		_links.append(link)
