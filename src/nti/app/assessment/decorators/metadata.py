#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver.interfaces import IUser

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link
from nti.links.externalization import render_link

from ..common import get_assessment_metadata_item

from . import _get_course_from_assignment
from . import _AbstractTraversableLinkDecorator

LINKS = StandardExternalFields.LINKS

class _AssignmentMetadataDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, assignment, result):
		user = self.remoteUser
		course = _get_course_from_assignment(assignment, user)
		if course is None:
			return
		
		elements = ('AssignmentMetadata', user.username, assignment.ntiid, 'Metadata')

		links = result.setdefault(LINKS, [])
		links.append( Link( course,
							rel='Metadata',
							elements=elements))
			
		if IQTimedAssignment.providedBy(assignment):
			item = get_assessment_metadata_item(course, self.remoteUser, assignment)	
			if item is None or item.StartTime is None:
				links.append( Link( course,
									method='POST',
									rel='Commence',
									elements=elements + ('Commence',)))
			else:
				links.append( Link( course,
									method='GET',
									rel='StartTime',
									elements=elements + ('StartTime',)))
						
@interface.implementer(IExternalMappingDecorator)
class _AssignmentMetadataContainerDecorator(_AbstractTraversableLinkDecorator):
	
	def _do_decorate_external( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		user = IUser(context, self.remoteUser)
		links.append( Link( context,
							rel='AssignmentMetadata',
							elements=('AssignmentMetadata', user.username)) )

@interface.implementer(IExternalMappingDecorator)
class _AssignmentMetadataItemDecorator(AbstractAuthenticatedRequestAwareDecorator):
	
	def _predicate(self, context, result):
		creator = context.creator
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
				and creator is not None
				and creator == self.remoteUser)
		
	def _do_decorate_external(self, context, result_map ):
		try:
			link = Link(context)
			result_map['href'] = render_link( link )['href']
		except (KeyError, ValueError, AssertionError):
			pass # Nope
