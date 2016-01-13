#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.appserver.pyramid_authorization import has_permission

from nti.common.property import Lazy

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator
from nti.app.assessment.decorators import PreviewCourseAccessPredicateDecorator

LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _CourseEditorLinksDecorator(PreviewCourseAccessPredicateDecorator,
								  _AbstractTraversableLinkDecorator):

	@Lazy
	def _acl_decoration(self):
		result = getattr(self.request, 'acl_decoration', True)
		return result

	def _predicate(self, context, result):
		return 		self._acl_decoration \
				and self._is_authenticated \
				and has_permission(ACT_CONTENT_EDIT, context, self.request)

	def _do_decorate_external(self, context, result_map):
		links = result_map.setdefault(LINKS, [])
		links.append(Link(context, rel='Inquiries', elements=('@@Inquiries')))
		links.append(Link(context, rel='Assessments', elements=('@@Assessments')))
		links.append(Link(context, rel='Assignments', elements=('@@Assignments')))
