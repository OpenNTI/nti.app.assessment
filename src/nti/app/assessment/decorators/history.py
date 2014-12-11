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

from nti.app.products.courseware.utils import is_course_instructor

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.links import Link
from nti.dataserver.interfaces import IUser
from nti.dataserver.traversal import find_interface

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.utils.property import Lazy

from ..common import get_assessment_metadata_item

from . import _get_course_from_assignment
from . import _AbstractTraversableLinkDecorator
					
LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _CourseAssignmentHistoryDecorator(_AbstractTraversableLinkDecorator):
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

@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryLinkDecorator(_AbstractTraversableLinkDecorator):

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result
		
	def _do_decorate_external( self, context, result_map ):
		user = self.remoteUser
		course = _get_course_from_assignment(context, user, self._catalog)
		if course is not None:
			links = result_map.setdefault( LINKS, [] )
			links.append( Link( course,
								rel='History',
								elements=('AssignmentHistories', user.username,
										   context.ntiid)) )

@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemDecorator(_AbstractTraversableLinkDecorator):
	
	def _do_decorate_external( self, context, result_map ):
		user = self.remoteUser
		course = find_interface(context, ICourseInstance, strict=False)
		if course is None or is_course_instructor(course, user):
			return
		item = get_assessment_metadata_item(course, user, context.assignmentId)
		if item is not None:
			result_map['Metadata'] = to_external_object(item)
