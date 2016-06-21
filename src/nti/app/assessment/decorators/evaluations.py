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
from nti.app.assessment import VIEW_RESET_EVALUATION

from nti.app.assessment.decorators import _get_course_from_evaluation

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.authorization import ACT_CONTENT_EDIT, ACT_NTI_ADMIN

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _EvaluationLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		return self._is_authenticated 

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])
	
		if has_permission(ACT_CONTENT_EDIT, context, self.request):
			link = Link(context, rel=VIEW_COPY_EVALUATION,
						elements=('@@' + VIEW_COPY_EVALUATION,),
						method='POST')
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)

		course = _get_course_from_evaluation(context, 
											 user=self.remoteUser, 
											 request=self.request)
		if 	context.is_published() \
			and (	(course is not None and is_course_instructor(course, self.remoteUser)) \
			 	 or	has_permission(ACT_NTI_ADMIN, context, self.request) ):
			link = Link(context, rel=VIEW_RESET_EVALUATION,
						elements=('@@' + VIEW_RESET_EVALUATION,), 
						method='DELETE')
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)
