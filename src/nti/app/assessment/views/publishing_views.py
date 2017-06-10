#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import get_courses

from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import validate_structural_edits

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH

from nti.app.publishing.views import CalendarPublishView
from nti.app.publishing.views import CalendarUnpublishView

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver import authorization as nauth

from nti.publishing.interfaces import ICalendarPublishable

from nti.traversal.traversal import find_interface


def publish_context(context, start=None, end=None):
    # publish
    if not context.is_published():
        if ICalendarPublishable.providedBy(context):
            context.publish(start=start, end=end)
        else:
            context.publish()
    # register utility
    register_context(context)
    # process 'children'
    if IQEvaluationItemContainer.providedBy(context):
        for item in context.Items or ():
            publish_context(item, start, end)
    elif IQAssignment.providedBy(context):
        for item in context.iter_question_sets():
            publish_context(item, start, end)


@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               name=VIEW_PUBLISH,
               permission=nauth.ACT_UPDATE,
               request_method='POST')
class EvaluationPublishView(CalendarPublishView):

    def _do_provide(self, context):
        if IQEditableEvaluation.providedBy(context):
            start, end = self._get_dates()
            publish_context(context, start, end)


@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               name=VIEW_UNPUBLISH,
               permission=nauth.ACT_UPDATE,
               request_method='POST')
class EvaluationUnpublishView(CalendarUnpublishView):

    def _do_provide(self, context):
        if IQEditableEvaluation.providedBy(context):
            course = find_interface(context, ICourseInstance, strict=True)
            for course in get_courses(course):
                # Not allowed to unpublish if we have submissions/savepoints.
                validate_structural_edits(context, course)
            # unpublish
            super(EvaluationUnpublishView, self)._do_provide(context)
