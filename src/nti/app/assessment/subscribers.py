#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Event handlers.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.app.products.courseware.interfaces import ICourseInstanceActivity
from nti.dataserver.traversal import find_interface


def add_object_to_course_activity(submission, event):
	"""This can be registered for anything we want to submit to course activity
	as a subscriber to :class:`zope.intid.interfaces.IIntIdAddedEvent`"""
	course = find_interface(submission, ICourseInstance)
	activity = ICourseInstanceActivity(course)
	activity.append(submission)


def remove_object_from_course_activity(submission, event):
	"""This can be registered for anything we want to submit to course activity
	as a subscriber to :class:`zope.intid.interfaces.IIntIdRemovedEvent`"""
	course = find_interface(submission, ICourseInstance)
	activity = ICourseInstanceActivity(course)
	activity.remove(submission)
