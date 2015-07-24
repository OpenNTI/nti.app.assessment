#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
from nti.app.assessment.common import can_disclose_inquiry
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.app.products.courseware.utils import is_course_instructor

from nti.assessment.interfaces import IQSurvey

from nti.common.property import Lazy

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses.interfaces import ICourseCatalog

from nti.dataserver.interfaces import IUser

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link
from nti.links.externalization import render_link

from nti.traversal.traversal import find_interface

from . import _root_url
from . import _get_course_from_assignment
from . import _AbstractTraversableLinkDecorator

LINKS = StandardExternalFields.LINKS

class _InquiryContentRootURLAdder(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, context, result):
		ntiid = getattr(context, 'ContentUnitNTIID', None)
		if not ntiid:
			content_unit = find_interface(context, IContentUnit, strict=False)
			if content_unit is not None:
				ntiid = content_unit.ntiid
			else:
				assignment = find_interface(context, IQSurvey, strict=False)
				ntiid = getattr(assignment, 'ContentUnitNTIID', None)

		bucket_root = _root_url(ntiid) if ntiid else None
		if bucket_root:
			result['ContentRoot' ] = bucket_root

@interface.implementer(IExternalMappingDecorator)
class _InquiriesDecorator(_AbstractTraversableLinkDecorator):

	def _do_decorate_external( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		user = IUser(context, self.remoteUser)
		links.append( Link( context,
							rel='Inquiries',
							elements=('Inquiries', user.username)) )

@interface.implementer(IExternalMappingDecorator)
class _InquiryItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

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

@interface.implementer(IExternalMappingDecorator)
class _InquiryHistoryLinkDecorator(_AbstractTraversableLinkDecorator):

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
								rel='InquiryHistories',
								elements=('InquiryHistories', user.username,
										   context.ntiid)) )

@interface.implementer(IExternalMappingDecorator)
class _AggregatedInquiryLinkDecorator(_AbstractTraversableLinkDecorator):

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result
		
	def _do_decorate_external( self, context, result_map ):
		user = self.remoteUser
		course = _get_course_from_assignment(context, user, self._catalog)
		if 	course is not None and \
			(is_course_instructor(course, user) or can_disclose_inquiry(context)):
			links = result_map.setdefault( LINKS, [] )
			links.append( Link( context,
								rel='Aggregated',
								elements=('Aggregated')) )
