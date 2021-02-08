#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from collections import Mapping

from pyramid.interfaces import IRequest
from zope import component
from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_QUESTION_CONTAINERS

from nti.app.assessment.common.containers import get_outline_evaluation_containers

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import _get_package_from_evaluation
from nti.app.assessment.decorators import AbstractSolutionStrippingDecorator

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQPart
from nti.assessment.interfaces import IQuestion

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


@component.adapter(IQuestion)
@interface.implementer(IExternalObjectDecorator)
class QuestionContainerDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    Add an `Assessments` link to fetch all assignments and question sets
    containing our given question context and add a `AssessmentContainerCount`.
    """

    def _predicate(self, context, unused_result):
        return  self._is_authenticated \
            and has_permission(ACT_CONTENT_EDIT, context, self.request)

    def composite(self, context):
        result = _get_package_from_evaluation(context, self.request)
        if result is None:
            result = _get_course_from_evaluation(context, self.remoteUser,
                                                 request=self.request)
        return result

    def _do_decorate_external(self, context, result):
        containers = get_outline_evaluation_containers(context)
        result['AssessmentContainerCount'] = len(containers or ())

        composite = self.composite(context)
        link_context = context if composite is None else composite
        pre_elements = () if composite is None else ('Assessments', context.ntiid)

        _links = result.setdefault(LINKS, [])
        link = Link(link_context,
                    rel=VIEW_QUESTION_CONTAINERS,
                    elements=pre_elements + ('@@%s' % VIEW_QUESTION_CONTAINERS,))
        interface.alsoProvides(link, ILocation)
        link.__name__ = ''
        link.__parent__ = link_context
        _links.append(link)


class QuestionPartStripperMixin(object):

    def strip_question_part(self, part, max_submission_strip):
        """
        Strip solutions and explanation. Also, strip correctness (if available)
        if we have an assessedValue val.
        """
        if isinstance(part, Mapping):
            for key in ('solutions', 'explanation'):
                if key in part:
                    part[key] = None
            if max_submission_strip:
                part.pop('assessedValue', None)


@component.adapter(IQPart, IRequest)
@interface.implementer(IExternalObjectDecorator)
class QuestionPartStripper(AbstractSolutionStrippingDecorator,
                           QuestionPartStripperMixin):

    def _do_decorate_external(self, context, result):
        self.strip_question_part(result, True)
