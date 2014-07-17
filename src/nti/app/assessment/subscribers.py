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

from zope import component

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.assessment.interfaces import IQAssignmentDateContext

from nti.contentlibrary.interfaces import IContentPackageLibrary

from pyramid.httpexceptions import HTTPUnprocessableEntity

import simplejson as json
from datetime import datetime

from . import MessageFactory as _
from nti.externalization.externalization import to_external_object

from .adapters import _find_course_for_assignment

def prevent_note_on_assignment_part(note, event):
	"""
	When we try to create a note on something related to an
	assignment, don't, unless it's after the due date.

	This includes:

		* The main containing page
		* The assignment itself
		* Any question or part within the assignment

	This works only as long as assignments reference a question set
	one and only one time and they are always authored together on the
	same page.
	"""

	container_id = note.containerId


	# Find an assignment or part of one
	item = None
	items = ()
	for iface in IQAssignment, IQuestion, IQuestionSet:
		item = component.queryUtility(iface,name=container_id)
		if item is not None:
			items = (item,)
			break

	if IQuestion.providedBy(item) or IQuestionSet.providedBy(item):
		parent = item.__parent__
		if parent:
			# Ok, we found the content unit defining this question.
			# If that content unit has any assignments in it,
			# no notes, regardless of whether this particular
			# question was used in the assignment. So
			# restart the lookup at the container level
			container_id = parent.ntiid
			item = None

	if item is None:
		# Look for a page
		library = component.getUtility(IContentPackageLibrary)
		path = library.pathToNTIID(container_id)
		if path:
			item = path[-1]
			item = IQAssessmentItemContainer(item, ())
			items = [x for x in item if IQAssignment.providedBy(x)]

	if not items:
		return

	remoteUser = note.creator

	for asg in items:
		if IQAssignment.providedBy(asg):
			course = _find_course_for_assignment(asg, remoteUser, exc=False)
			if course:
				dates = IQAssignmentDateContext(course).of(asg)
			else:
				dates = asg

			if dates.available_for_submission_ending and dates.available_for_submission_ending >= datetime.utcnow():
				e = HTTPUnprocessableEntity()
				e.text = json.dumps({'message': _("You cannot make notes on an assignment before the due date."),
									 'code': 'CannotNoteOnAssignmentBeforeDueDate',
									 'available_for_submission_ending': to_external_object(dates.available_for_submission_ending)},
									ensure_ascii=False)
				e.content_type = b'application/json'
				raise e
