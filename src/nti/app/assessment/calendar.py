#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from nti.schema.field import Object

from zope import component
from zope import interface

from nti.zope_catalog.interfaces import INoAutoIndexEver

from nti.app.products.courseware.calendar.model import CourseCalendarEvent
from nti.app.products.courseware.calendar.interfaces import ICourseCalendarDynamicEvent
from nti.app.products.courseware.calendar.interfaces import ICourseCalendarDynamicEventProvider

from nti.app.assessment.common.utils import get_available_for_submission_ending

from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.completion.utils import get_completable_items_for_user

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser

from nti.externalization.persistence import NoPickle

from nti.externalization.datastructures import InterfaceObjectIO

from nti.schema.fieldproperty import createDirectFieldProperties


class IAssignmentCalendarEvent(ICourseCalendarDynamicEvent):

    assignment = Object(IQAssignment,
                        title=u"The assignment this event refers to.",
                        required=True)


@NoPickle
@interface.implementer(IAssignmentCalendarEvent)
class AssignmentCalendarEvent(CourseCalendarEvent):

    __external_can_create__ = False

    __external_class_name__ = "AssignmentCalendarEvent"

    mimeType = mime_type = "application/vnd.nextthought.assessment.assignmentcalendarevent"

    createDirectFieldProperties(IAssignmentCalendarEvent)


class AssignmentCalendarEventIO(InterfaceObjectIO):

    _ext_iface_upper_bound = IAssignmentCalendarEvent


@component.adapter(IUser, ICourseInstance)
@interface.implementer(ICourseCalendarDynamicEventProvider)
class AssignmentCalendarDynamicEventProvider(object):

    def __init__(self, user, course):
        self.user = user
        self.course = course

    def iter_events(self):
        res = []
        for assign in self._assignments(self.user, self.course):
            # only show those have due date assignment events.
            start_time = get_available_for_submission_ending(assign, self.course)
            if start_time:
                event = AssignmentCalendarEvent(title=assign.title,
                                                description=assign.content,
                                                start_time=start_time,
                                                assignment=assign)
                res.append(event)
        return res

    def _assignments(self, user, course):
        items = get_completable_items_for_user(user, course) or ()
        return [x for x in items if IQAssignment.providedBy(x)]
