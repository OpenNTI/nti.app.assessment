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

from zope.intid import IIntIds

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.common.property import Lazy

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.interfaces import IUser

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link
from nti.links.externalization import render_link

from nti.traversal.traversal import find_interface

from ..common import can_disclose_inquiry
from ..common import get_policy_for_assessment
from ..common import get_available_for_submission_ending
from ..common import get_available_for_submission_beginning

from ..interfaces import IUsersCourseInquiry

from ..index import IX_COURSE
from ..index import IX_ASSESSMENT_ID

from .. import get_assesment_catalog

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

	def _do_decorate_external(self, context, result_map):
		links = result_map.setdefault(LINKS, [])
		user = IUser(context, self.remoteUser)
		links.append(Link(context,
						  rel='InquiryHistory',
						  elements=('Inquiries', user.username)))

@interface.implementer(IExternalMappingDecorator)
class _InquiryItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

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

@interface.implementer(IExternalMappingDecorator)
class _InquiryDecorator(_AbstractTraversableLinkDecorator):

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result

	@Lazy
	def _intids(self):
		result = component.getUtility(IIntIds)
		return result

	def _submissions(self, course, context):
		catalog = get_assesment_catalog()
		course = ICourseInstance(course)
		doc_id = self._intids.getId(course)
		query = { IX_COURSE: {'any_of':(doc_id,)},
				  IX_ASSESSMENT_ID : {'any_of':(context.ntiid,)}}
		result = catalog.apply(query) or ()
		return len(result)

	def _predicate(self, context, result):
		context = IQInquiry(context, None)
		if context is not None:
			return super(_InquiryDecorator, self)._predicate(context, result)
		return False

	def _do_decorate_external(self, context, result_map):
		source = context
		context = IQInquiry(source, None)
		if context is None:
			return

		result_map['isClosed'] = bool(context.closed)

		user = self.remoteUser
		links = result_map.setdefault(LINKS, [])
		course = _get_course_from_assignment(context, user, self._catalog)
		
		submissions = self._submissions(course, context) if course is not None else 0
		
		# overrides
		if course is not None:
			dates = IQAssessmentDateContext(course).of(context)
			for k, func in ( 
					('available_for_submission_ending', get_available_for_submission_ending),
					('available_for_submission_beginning', get_available_for_submission_beginning)):
				dates_date = func(dates, k)
				asg_date = getattr(context, k)
				if dates_date != asg_date:
					result_map[k] = to_external_object(dates_date)

			policy = get_policy_for_assessment(context, course)
			if policy and 'disclosure' in policy:
				result_map['disclosure'] = policy['disclosure']

			result_map['submissions'] = submissions

		elements = ('Inquiries', user.username, context.ntiid)

		course_inquiry = component.queryMultiAdapter((course, user),
													 IUsersCourseInquiry)
		# history
		if course is not None and course_inquiry and context.ntiid in course_inquiry:
			links.append(Link(course,
							  rel='History',
							  elements=elements + ('Submission',)))

		# aggregated
		if 	course is not None and submissions and \
			(is_course_instructor(course, user) or can_disclose_inquiry(context, course)):
			links.append(Link(course,
							  rel='Aggregated',
							  elements=elements + ('Aggregated',)))

		# close/open
		if course is not None and is_course_instructor(course, user):
			if not context.closed:
				links.append(Link(course,
								  rel='close',
								  method='POST',
								  elements=elements + ('close',)))
			else:
				links.append(Link(course,
								  rel='open',
								  method='POST',
								  elements=elements + ('open',)))
