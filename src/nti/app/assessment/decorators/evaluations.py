#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_COPY_EVALUATION
from nti.app.assessment import VIEW_RESET_EVALUATION

from nti.app.assessment.common.evaluations import is_global_evaluation

from nti.app.assessment.common.history import has_savepoints

from nti.app.assessment.common.submissions import has_submissions
from nti.app.assessment.common.submissions import has_inquiry_submissions

from nti.app.assessment.common.utils import get_courses

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import _get_package_from_evaluation

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import get_course_from_evaluation

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

from nti.dataserver.interfaces import ILinkExternalHrefOnly

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


def _has_any_submissions(context, course):
    courses = get_courses(course)
    if IQInquiry.providedBy(context):
        submissions = has_inquiry_submissions(context, course)
    else:
        submissions = has_submissions(context, courses)
    return bool(submissions or has_savepoints(context, courses))


@interface.implementer(IExternalMappingDecorator)
class _EvaluationLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, unused_context, unused_result):
        return self._is_authenticated

    def composite(self, context):
        result = _get_package_from_evaluation(context, self.request)
        if result is None:
            result = _get_course_from_evaluation(context, self.remoteUser,
                                                 request=self.request)
        return result

    def _do_decorate_external(self, context, result):
        _links = result.setdefault(LINKS, [])

        composite = self.composite(context)

        link_context = context if composite is None else composite
        pre_elements = () if composite is None else ('Assessments', context.ntiid)

        context_link = Link(link_context, elements=pre_elements)
        interface.alsoProvides(context_link, ILinkExternalHrefOnly)
        result['href'] = context_link

        if      not is_global_evaluation(context) \
            and has_permission(ACT_CONTENT_EDIT, context, self.request):
            link = Link(link_context,
                        rel=VIEW_COPY_EVALUATION,
                        elements=pre_elements + ('@@' + VIEW_COPY_EVALUATION,),
                        method='POST')
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = context
            _links.append(link)

        if      ICourseInstance.providedBy(composite) \
            and is_course_instructor(composite, self.remoteUser) \
            and _has_any_submissions(context, composite):
            link = Link(link_context,
                        rel=VIEW_RESET_EVALUATION,
                        elements=pre_elements +
                        ('@@' + VIEW_RESET_EVALUATION,),
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

    def _predicate(self, context, unused_result):
        # For content-backed items, make sure we do not provide pub/unpub
        # links.
        if not IQEditableEvaluation.providedBy(context):
            return True
        course = get_course_from_request()
        if course is None:
            course = get_course_from_evaluation(context)
        return _has_any_submissions(context, course)


@interface.implementer(IExternalObjectDecorator)
class _ContentBackedAssignmentEditLinkRemover(EditLinkRemoverDecorator):
    """
    Removes edit links from content backed assignments.
    """

    def _predicate(self, context, unused_result):
        return not IQEditableEvaluation.providedBy(context)
