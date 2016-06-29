#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_COPY_EVALUATION
from nti.app.assessment import VIEW_RESET_EVALUATION

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import has_inquiry_submissions

from nti.app.assessment.decorators import _get_course_from_evaluation

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.authorization import ACT_NTI_ADMIN
from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _EvaluationLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		return self._is_authenticated

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])

		if has_permission(ACT_CONTENT_EDIT, context, self.request):
			link = Link(context, rel=VIEW_COPY_EVALUATION,
						elements=('@@' + VIEW_COPY_EVALUATION,),
						method='POST')
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)

		course = _get_course_from_evaluation(context,
											 user=self.remoteUser,
											 request=self.request)
		if 	context.is_published() \
			and ((course is not None and is_course_instructor(course, self.remoteUser)) \
			 	 or	has_permission(ACT_NTI_ADMIN, context, self.request)):
			link = Link(context, rel=VIEW_RESET_EVALUATION,
						elements=('@@' + VIEW_RESET_EVALUATION,),
						method='DELETE')
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)

@interface.implementer(IExternalObjectDecorator)
class _EvaluationCalendarPublishStateDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Removes publish links from the evaluation if we have any submissions.
	"""

	def _get_course(self, context):
		course = find_interface(context, ICourseInstance, strict=False)
		return course

	def _predicate(self, context, result):
		# For content-backed items, make sure we do not provide pub/unpub links.
		if not IQEditableEvaluation.providedBy( context ):
			return True
		course = self._get_course(context)
		if IQInquiry.providedBy(context):
			submissions = has_inquiry_submissions( context, course )
		else:
			courses = get_courses( course )
			submissions = has_submissions( context, courses )
		return submissions

	def _do_decorate_external(self, context, result):
		# Remove any publish/unpublish links.
		publish_rels = (VIEW_PUBLISH, VIEW_UNPUBLISH)
		_links = result.setdefault(LINKS, [])
		new_links = []
		for link in _links:
			# Some links may be externalized already.
			rel = ''
			try:
				rel = link.rel
			except AttributeError:
				try:
					rel = link.get('rel')
				except AttributeError:
					pass
			if rel not in publish_rels:
				new_links.append(link)
		result[LINKS] = new_links
