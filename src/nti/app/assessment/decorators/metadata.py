#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.common import get_assessment_metadata_item

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver.interfaces import IUser

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.externalization import render_link

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

class _AssignmentMetadataDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, assignment, result):
		user = self.remoteUser
		course = _get_course_from_evaluation(assignment, user, request=self.request)
		if course is None:
			return

		elements = ('AssignmentMetadata', user.username, assignment.ntiid)

		links = result.setdefault(LINKS, [])
		links.append(Link(course,
						  rel='Metadata',
						  elements=elements + ('Metadata',)))

		if IQTimedAssignment.providedBy(assignment):
			item = get_assessment_metadata_item(course, self.remoteUser, assignment)
			if item is None or item.StartTime is None:
				links.append(Link(course,
								  method='POST',
								  rel='Commence',
								  elements=elements + ('Commence',)))
			else:
				for rel in ('StartTime', 'TimeRemaining'):
					links.append(Link(course,
								  	  method='GET',
								  	  rel=rel,
								  	  elements=elements + (rel,)))

@interface.implementer(IExternalMappingDecorator)
class _AssignmentMetadataContainerDecorator(AbstractAssessmentDecoratorPredicate):

	def _do_decorate_external(self, context, result_map):
		links = result_map.setdefault(LINKS, [])
		user = IUser(context, self.remoteUser)
		links.append(Link(context,
						  rel='AssignmentMetadata',
						  elements=('AssignmentMetadata', user.username)))

@interface.implementer(IExternalMappingDecorator)
class _AssignmentMetadataItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		creator = context.creator
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
				and creator is not None
				and creator == self.remoteUser)

	def _do_decorate_external(self, context, result_map):
		try:
			link = Link(context)
			result_map['href'] = render_link(link)['href']
		except (KeyError, ValueError, AssertionError):
			pass  # Nope
