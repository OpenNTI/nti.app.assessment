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

from nti.app.assessment.common import get_assessment_metadata_item

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.interfaces import IUser

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.property.property import Lazy

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _AssignmentsAvailableAssignmentHistoryDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	For a user's assignment history, expose available assignments.
	"""

	def _do_decorate_external(self, context, result_map):
		user = context.owner
		course = find_interface(context, ICourseInstance, strict=False)
		if course is not None:
			assignment_catalog = ICourseAssignmentCatalog(course)
			user_predicate = get_course_assessment_predicate_for_user(user, course)
			result_map['AvailableAssignmentNTIIDs'] = [
				asg.ntiid 
				for asg in assignment_catalog.iter_assignments() if user_predicate(asg)
			]

@interface.implementer(IExternalMappingDecorator)
class _CourseAssignmentHistoryDecorator(AbstractAssessmentDecoratorPredicate):
	"""
	For things that have an assignment history, add this as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor.

	def _do_decorate_external(self, context, result_map):
		links = result_map.setdefault(LINKS, [])
		# XXX: If the context provides a user, that's the one we want,
		# otherwise we want the current user
		user = IUser(context, self.remoteUser)
		links.append(Link(context,
						  rel='AssignmentHistory',
						  elements=('AssignmentHistories', user.username)))

class _LastViewedAssignmentHistoryDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	For assignment histories, when the requester is the owner,
	we add a link to point to the 'lastViewed' update spot.
	"""

	def _predicate(self, context, result):
		return (self._is_authenticated
				and context.owner is not None
				and context.owner == self.remoteUser)

	def _do_decorate_external(self, context, result):
		links = result.setdefault(LINKS, [])
		links.append(Link(context,
						  rel='lastViewed',
						  elements=('@@lastViewed',),
						  method='PUT'))

@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryLinkDecorator(_AbstractTraversableLinkDecorator):

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result

	def _do_decorate_external(self, context, result_map):
		user = self.remoteUser
		course = _get_course_from_evaluation(context,
											 user,
											 self._catalog,
											 request=self.request)
		history = component.queryMultiAdapter((course, user),
											  IUsersCourseAssignmentHistory)
		if history and context.ntiid in history:
			links = result_map.setdefault(LINKS, [])
			links.append(Link(course,
							  rel='History',
							  elements=('AssignmentHistories', user.username,
										context.ntiid)))

@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemDecorator(_AbstractTraversableLinkDecorator):

	def _do_decorate_external(self, context, result_map):
		creator = context.creator
		remoteUser = self.remoteUser
		course = find_interface(context, ICourseInstance, strict=False)
		if course is None:
			return
		user = creator if is_course_instructor(course, remoteUser) else remoteUser
		item = get_assessment_metadata_item(course, user, context.assignmentId)
		if item is not None:
			result_map['Metadata'] = to_external_object(item)
