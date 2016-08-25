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
from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import has_inquiry_submissions

from nti.app.assessment.decorators import _get_course_from_evaluation

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission
from nti.appserver.pyramid_renderers_edit_link_decorator import LinkRemoverDecorator
from nti.appserver.pyramid_renderers_edit_link_decorator import EditLinkRemoverDecorator

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS

def _has_any_submissions(context, course):
	courses = get_courses(course)
	if IQInquiry.providedBy(context):
		submissions = has_inquiry_submissions(context, course)
	else:
		submissions = has_submissions(context, courses)
	return submissions or has_savepoints(context, courses)

@interface.implementer(IExternalMappingDecorator)
class _EvaluationLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		return self._is_authenticated

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])

		course = _get_course_from_evaluation(context,
											 user=self.remoteUser,
											 request=self.request)

		link_context = context if course is None else course
		pre_elements = () if course is None else ('Assessments', context.ntiid)
		
		if has_permission(ACT_CONTENT_EDIT, context, self.request):
			link = Link(link_context, rel=VIEW_COPY_EVALUATION,
						elements=pre_elements + ('@@' + VIEW_COPY_EVALUATION,),
						method='POST')
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)

		if 		course is not None \
			and context.is_published() \
			and is_course_instructor(course, self.remoteUser) \
			and _has_any_submissions(context, course):
			link = Link(link_context, rel=VIEW_RESET_EVALUATION,
						elements=pre_elements + ('@@' + VIEW_RESET_EVALUATION,),
						method='POST')
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)

@interface.implementer(IExternalObjectDecorator)
class _EvaluationCalendarPublishStateDecorator(LinkRemoverDecorator):
	"""
	Removes publish links from the evaluation if we have any savepoints
	or submissions.
	"""

	links_to_remove = (VIEW_PUBLISH, VIEW_UNPUBLISH)

	def _predicate(self, context, result):
		# For content-backed items, make sure we do not provide pub/unpub links.
		if not IQEditableEvaluation.providedBy(context):
			return True
		course = find_interface(context, ICourseInstance, strict=True)
		return _has_any_submissions(context, course)

@interface.implementer(IExternalObjectDecorator)
class _ContentBackedAssignmentEditLinkRemover(EditLinkRemoverDecorator):
	"""
	Removes edit links from content backed assignments.
	"""

	def _predicate(self, context, result):
		return not IQEditableEvaluation.providedBy(context)
