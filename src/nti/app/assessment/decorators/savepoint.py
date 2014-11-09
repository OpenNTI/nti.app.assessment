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

from nti.dataserver.links import Link
from nti.dataserver.interfaces import IUser
from nti.dataserver.links_external import render_link

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from . import _get_course_from_assignment
from . import _AbstractTraversableLinkDecorator

LINKS = StandardExternalFields.LINKS

class _AssignmentSavepointDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, assignment, result):
		course = _get_course_from_assignment(assignment, self.remoteUser)
		if course is not None:
			links = result.setdefault(LINKS, [])
			links.append( Link( assignment,
								rel='Savepoint',
								elements=('Savepoint',)))
					
@interface.implementer(IExternalMappingDecorator)
class _AssignmentSavepointsDecorator(_AbstractTraversableLinkDecorator):
	
	def _do_decorate_external( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		user = IUser(context, self.remoteUser)
		links.append( Link( context,
							rel='AssignmentSavepoints',
							elements=('AssignmentSavepoints', user.username)) )

@interface.implementer(IExternalMappingDecorator)
class _AssignmentSavepointItemDecorator(AbstractAuthenticatedRequestAwareDecorator):
	
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

	