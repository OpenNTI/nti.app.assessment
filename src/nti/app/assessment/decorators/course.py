#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.common.property import Lazy

from nti.contenttypes.courses.utils import is_course_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _CourseEditorLinksDecorator(_AbstractTraversableLinkDecorator):

	@Lazy
	def _acl_decoration(self):
		result = getattr(self.request, 'acl_decoration', True)
		return result

	def _predicate(self, context, result):
		return (	super(_CourseEditorLinksDecorator,self)._predicate(context, result)
				and self._acl_decoration
				and (	is_course_editor(context, self.remoteUser)
					 or has_permission(ACT_CONTENT_EDIT, context, self.request)))

	def _do_decorate_external(self, context, result_map):
		links = result_map.setdefault(LINKS, [])
		links.append(Link(context, rel='Inquiries', elements=('@@Inquiries',)))
		links.append(Link(context, rel='Assessments', elements=('@@Assessments',)))
		links.append(Link(context, rel='Assignments', elements=('@@Assignments',)))
		links.append(Link(context, rel='CourseEvaluations', elements=('CourseEvaluations',)))
