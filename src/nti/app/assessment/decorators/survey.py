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

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.app.products.courseware.utils import is_course_instructor

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.common.property import Lazy

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses.interfaces import ICourseCatalog

from nti.dataserver.interfaces import IUser

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link
from nti.links.externalization import render_link

from nti.traversal.traversal import find_interface

from ..common import can_disclose_inquiry
from ..common import get_policy_for_assessment

from ..interfaces import IUsersCourseInquiry

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
							rel='InquiryHistory',
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
class _InquiryLinkDecorator(_AbstractTraversableLinkDecorator):

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result
		
	def _do_decorate_external( self, context, result_map):
		context = IQInquiry(context, None)
		if context is None:
			return

		user = self.remoteUser
		links = result_map.setdefault( LINKS, [] )
		course = _get_course_from_assignment(context, user, self._catalog)
		
		# overrides
		if course is not None:
			dates = IQAssessmentDateContext(course).of(context)
			for k in ('available_for_submission_ending',
					  'available_for_submission_beginning'):
				asg_date = getattr(context, k)
				dates_date = getattr(dates, k)
				if dates_date != asg_date:
					result_map[k] = to_external_object(dates_date)
	
			policy = get_policy_for_assessment(course, context)
			if policy and 'disclosure' in policy:
				result_map['disclosure'] = policy['disclosure']
			
		elements=('Inquiries', user.username, context.ntiid)
		
		course_inquiry = component.queryMultiAdapter((course, user), 
													 IUsersCourseInquiry)
		# history
		if course is not None and course_inquiry and context.ntiid in course_inquiry:
			links.append( Link( course,
								rel='History',
								elements=elements) )
			
		# aggregated
		if 	course is not None and \
			(is_course_instructor(course, user) or can_disclose_inquiry(context, course)):
			links.append( Link( course,
								rel='Aggregated',
								elements=elements + ('Aggregated',)) )
			
		# close/open
		if course is not None and is_course_instructor(course, user):
			if not context.closed:
				links.append( Link( course,
									rel='close',
									method='POST',
									elements=elements + ('close',)) )
			else:
				links.append( Link( course,
									rel='open',
									method='POST',
									elements=elements + ('open',)) )
