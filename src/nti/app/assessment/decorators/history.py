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

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from . import _AbstractTraversableLinkDecorator
					
LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemDecorator(_AbstractTraversableLinkDecorator):
	"""
	For things that have an assignment history, add this
	as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor.

	def _do_decorate_external( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		# If the context provides a user, that's the one we want,
		# otherwise we want the current user
		user = IUser(context, self.remoteUser)
		links.append( Link( context,
							rel='AssignmentHistory',
							elements=('AssignmentHistories', user.username)) )

class _LastViewedAssignmentHistoryDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	For assignment histories, when the requester is the owner,
	we add a link to point to the 'lastViewed' update spot.
	"""

	def _predicate(self, context, result):
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
				and context.owner is not None
				and context.owner == self.remoteUser)

	def _do_decorate_external(self, context, result):
		links = result.setdefault( LINKS, [] )
		links.append( Link( context,
							rel='lastViewed',
							elements=('lastViewed',),
							method='PUT' ) )

