#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from . import MessageFactory as _

from datetime import datetime
from functools import partial

import simplejson

from zope import component

from zope.intid.interfaces import IIntIds
from zope.intid.interfaces import IIntIdRemovedEvent

from pyramid.httpexceptions import HTTPUnprocessableEntity

from nti.app.products.courseware.interfaces import ICourseInstanceActivity

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import ASSESSMENT_INTERFACES

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments

from nti.dataserver.interfaces import IUser
from nti.dataserver.users.interfaces import IWillDeleteEntityEvent

from nti.externalization.externalization import to_external_object

from nti.site.hostpolicy import run_job_in_all_host_sites

from nti.traversal.traversal import find_interface

from .common import get_unit_assessments
from .common import get_course_from_assignment
from .common import get_available_for_submission_ending

from .index import IX_COURSE
from .index import IX_CREATOR

from .interfaces import IUsersCourseInquiries
from .interfaces import IUsersCourseAssignmentHistories
from .interfaces import IUsersCourseAssignmentSavepoints
from .interfaces import IUsersCourseAssignmentSavepointItem
from .interfaces import IUsersCourseAssignmentMetadataContainer

from . import get_assesment_catalog

# activity / submission

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

# UGD

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
	for iface in ASSESSMENT_INTERFACES:
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
		library = component.queryUtility(IContentPackageLibrary)
		path = library.pathToNTIID(container_id) if library is not None else None
		if path:
			item = path[-1]
			items = get_unit_assessments(item)
			items = [x for x in items if IQAssignment.providedBy(x)]

	if not items:
		return

	remoteUser = note.creator

	for asg in items:
		if IQAssignment.providedBy(asg):
			course = get_course_from_assignment(asg, remoteUser)
			available_for_submission_ending = get_available_for_submission_ending(asg, course)
			if 	available_for_submission_ending and \
				available_for_submission_ending >= datetime.utcnow():
				e = HTTPUnprocessableEntity()
				e.text = simplejson.dumps(
						{'message': _("You cannot make notes on an assignment before the due date."),
						 'code': 'CannotNoteOnAssignmentBeforeDueDate',
						 'available_for_submission_ending':
						 		to_external_object(available_for_submission_ending)},
						ensure_ascii=False)
				e.content_type = b'application/json'
				raise e

# users

CONTAINER_INTERFACES = (IUsersCourseInquiries,
						IUsersCourseAssignmentHistories,
						IUsersCourseAssignmentSavepoints,
						IUsersCourseAssignmentMetadataContainer)

def delete_user_data(user):
	username = user.username
	for enrollments in component.subscribers((user,), IPrincipalEnrollments):
		for enrollment in enrollments.iter_enrollments():
			course = ICourseInstance(enrollment)
			for iface in CONTAINER_INTERFACES:
				user_data = iface(course, None)
				if user_data is not None and username in user_data:
					container = user_data[username]
					container.clear()
					del user_data[username]

def unindex_user_data(user):
	catalog = get_assesment_catalog()
	query = { IX_CREATOR: {'any_of':(user.username,)} }
	for uid in catalog.apply(query) or ():
		catalog.unindex_doc(uid)

@component.adapter(IUser, IWillDeleteEntityEvent)
def _on_user_will_be_removed(user, event):
	logger.info("Removing assignment data for user %s", user)
	run_job_in_all_host_sites(partial(delete_user_data, user=user))
	unindex_user_data(user)

# courses

def delete_course_data(course):
	for iface in CONTAINER_INTERFACES:
		user_data = iface(course, None)
		if user_data is not None:
			user_data.clear()

def unindex_course_data(course):
	intids = component.getUtility(IIntIds)
	uid = intids.queryId(course)
	if uid is not None:
		catalog = get_assesment_catalog()
		query = { IX_COURSE: {'any_of':(uid,)} }
		for uid in catalog.apply(query) or ():
			catalog.unindex_doc(uid)

@component.adapter(ICourseInstance, IIntIdRemovedEvent)
def on_course_instance_removed(course, event):
	delete_course_data(course)
	unindex_course_data(course)
