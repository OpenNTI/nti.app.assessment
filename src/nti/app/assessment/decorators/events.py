#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.location.interfaces import ILocation

from pyramid.interfaces import IRequest

from nti.app.assessment.common.evaluations import get_max_time_allowed

from nti.app.assessment.common.history import get_user_submission_count

from nti.app.assessment.common.policy import get_auto_grade_policy

from nti.app.assessment.calendar import IAssignmentCalendarEvent

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQTimedAssignment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.completion.utils import get_completed_item

from nti.externalization.interfaces import StandardExternalFields

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


@component.adapter(IAssignmentCalendarEvent, IRequest)
class _AssignmentEventDecorator(AbstractAuthenticatedRequestAwareDecorator):

    @Lazy
    def _catalog(self):
        result = component.getUtility(ICourseCatalog)
        return result

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, event, result):
        course = ICourseInstance(event, None)
        if course is None:
            return

        if IQTimedAssignment.providedBy(event.assignment):
            max_time_allowed = get_max_time_allowed(event.assignment, course)
            result['IsTimedAssignment'] = True
            result['MaximumTimeAllowed'] = max_time_allowed
        else:
            result['IsTimedAssignment'] = False

        auto_grade_policy = get_auto_grade_policy(event.assignment, course)
        total_points = auto_grade_policy.get('total_points')
        result['TotalPoints'] = result['total_points'] = total_points

        result['UserSubmissionCount'] = get_user_submission_count(self.remoteUser,
                                                                  course,
                                                                  event.assignment)

        result['HasSubmitted'] = bool(result['UserSubmissionCount'])
        completed_item = get_completed_item(self.remoteUser, course, event.assignment)
        if completed_item is not None:
            result['CompletedItem'] = completed_item

        _links = result.setdefault(LINKS, [])
        link = Link(course,
                    rel='Assignment',
                    elements=('Assessments', event.assignment.ntiid))
        interface.alsoProvides(link, ILocation)
        link.__name__ = ''
        link.__parent__ = course
        _links.append(link)
