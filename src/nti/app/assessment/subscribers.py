#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from . import MessageFactory as _

import simplejson
from datetime import datetime
from functools import partial

from zope import component

from pyramid.httpexceptions import HTTPUnprocessableEntity

from nti.app.products.courseware.interfaces import ICourseInstanceActivity

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentDateContext
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.indexed_data import get_catalog

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments

from nti.dataserver.interfaces import IUser
from nti.dataserver.users.interfaces import IWillDeleteEntityEvent

from nti.externalization.externalization import to_external_object

from nti.site.hostpolicy import run_job_in_all_host_sites

from nti.traversal.traversal import find_interface

from .common import get_course_from_assignment

from .interfaces import IUsersCourseInquiries
from .interfaces import IUsersCourseAssignmentHistories
from .interfaces import IUsersCourseAssignmentSavepoints
from .interfaces import IUsersCourseAssignmentSavepointItem
from .interfaces import IUsersCourseAssignmentMetadataContainer

def add_object_to_course_activity(submission, event):
	"""
	This can be registered for anything we want to submit to course activity
	as a subscriber to :class:`zope.intid.interfaces.IIntIdAddedEvent`
	"""
	if IUsersCourseAssignmentSavepointItem.providedBy(submission.__parent__):
		return

	course = find_interface(submission, ICourseInstance)
	activity = ICourseInstanceActivity(course)
	activity.append(submission)

def remove_object_from_course_activity(submission, event):
	"""
	This can be registered for anything we want to submit to course activity
	as a subscriber to :class:`zope.intid.interfaces.IIntIdRemovedEvent`
	"""
	if IUsersCourseAssignmentSavepointItem.providedBy(submission.__parent__):
		return

	course = find_interface(submission, ICourseInstance)
	activity = ICourseInstanceActivity(course)
	activity.remove(submission)

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

	item = None
	items = ()
	for iface in (IQSurvey, IQPoll, IQAssignment, IQuestion, IQuestionSet):
		item = component.queryUtility(iface, name=container_id)
		if item is not None:
			items = (item,)
			break

	if 	IQPoll.providedBy(item) or \
		IQuestion.providedBy(item) or \
		IQuestionSet.providedBy(item):

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
# 			catalog = get_catalog()
# 			items = catalog.search_objects( container_ntiids=item.ntiid )
			items = IQAssessmentItemContainer(item, ())
			items = [x for x in items if IQAssignment.providedBy(x)]

	if not items:
		return

	remoteUser = note.creator

	for asg in items:
		if IQAssignment.providedBy(asg):
			course = get_course_from_assignment(asg, remoteUser)
			if course:
				dates = IQAssignmentDateContext(course).of(asg)
			else:
				dates = asg

			if 	dates.available_for_submission_ending and \
				dates.available_for_submission_ending >= datetime.utcnow():
				e = HTTPUnprocessableEntity()
				e.text = simplejson.dumps(
						{'message': _("You cannot make notes on an assignment before the due date."),
						 'code': 'CannotNoteOnAssignmentBeforeDueDate',
						 'available_for_submission_ending':
						 		to_external_object(dates.available_for_submission_ending)},
						ensure_ascii=False)
				e.content_type = b'application/json'
				raise e

def delete_user_data(user):
	username = user.username
	for enrollments in component.subscribers((user,), IPrincipalEnrollments):
		for enrollment in enrollments.iter_enrollments():
			course = ICourseInstance(enrollment)
			for iface in (IUsersCourseInquiries,
						  IUsersCourseAssignmentHistories,
						  IUsersCourseAssignmentSavepoints,
						  IUsersCourseAssignmentMetadataContainer):
				user_data = iface(course, None)
				if user_data is not None and username in user_data:
					container = user_data[username]
					container.clear()
					del user_data[username]

@component.adapter(IUser, IWillDeleteEntityEvent)
def _on_user_will_be_removed(user, event):
	logger.info("Removing assignment data for user %s", user)
	func = partial(delete_user_data, user=user)
	run_job_in_all_host_sites(func)
