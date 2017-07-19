#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from datetime import datetime

import simplejson

from zope import component

from zope.container.interfaces import IContainer

from zope.intid.interfaces import IIntIds
from zope.intid.interfaces import IIntIdRemovedEvent

from pyramid.httpexceptions import HTTPUnprocessableEntity

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import get_unit_assessments
from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import get_course_from_evaluation
from nti.app.assessment.common import index_course_package_assessments
from nti.app.assessment.common import get_available_for_submission_ending

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import IX_CREATOR
from nti.app.assessment.index import get_submission_catalog

from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepointItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.app.products.courseware.interfaces import ICourseInstanceActivity

from nti.assessment import ASSESSMENT_INTERFACES

from nti.assessment.interfaces import TRX_QUESTION_MOVE_TYPE

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionMovedEvent

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses import get_enrollment_catalog

from nti.contenttypes.courses.index import IX_USERNAME

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseBundleUpdatedEvent

from nti.dataserver.interfaces import IUser

from nti.dataserver.users.interfaces import IWillDeleteEntityEvent

from nti.externalization.externalization import to_external_object

from nti.recorder.utils import record_transaction

from nti.traversal.traversal import find_interface


# activity / submission


def add_object_to_course_activity(submission, unused_event):
    """
    This can be registered for anything we want to submit to course activity
    as a subscriber to :class:`zope.intid.interfaces.IIntIdAddedEvent`
    """
    if IUsersCourseAssignmentSavepointItem.providedBy(submission.__parent__):
        return

    course = find_interface(submission, ICourseInstance)
    activity = ICourseInstanceActivity(course)
    activity.append(submission)


def remove_object_from_course_activity(submission, unused_event):
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


def prevent_note_on_assignment_part(note, unused_event):
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

    if     IQPoll.providedBy(item) \
        or IQuestion.providedBy(item) \
        or IQuestionSet.providedBy(item):

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
            course = get_course_from_evaluation(asg, remoteUser)
            available_for_submission_ending = get_available_for_submission_ending(asg, course)
            if      available_for_submission_ending \
                and available_for_submission_ending >= datetime.utcnow():
                e = HTTPUnprocessableEntity()
                e.text = simplejson.dumps(
                    {
                        'message': _(u"You cannot make notes on an assignment before the due date."),
                        'code': 'CannotNoteOnAssignmentBeforeDueDate',
                        'available_for_submission_ending':
                        to_external_object(available_for_submission_ending)
                    },
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
    catalog = get_enrollment_catalog()
    intids = component.getUtility(IIntIds)
    query = {IX_USERNAME: {'any_of': (username,)}}
    for uid in catalog.apply(query) or ():
        context = intids.queryObject(uid)
        course = ICourseInstance(context, None)
        if course is None:
            continue
        for iface in CONTAINER_INTERFACES:
            user_data = iface(course, None)
            if user_data is not None and username in user_data:
                container = user_data[username]
                if IContainer.providedBy(container):
                    container.clear()
                del user_data[username]


def unindex_user_data(user):
    catalog = get_submission_catalog()
    query = {IX_CREATOR: {'any_of': (user.username,)}}
    for uid in catalog.apply(query) or ():
        catalog.unindex_doc(uid)


@component.adapter(IUser, IWillDeleteEntityEvent)
def _on_user_will_be_removed(user, unused_event):
    logger.info("Removing assignment data for user %s", user)
    delete_user_data(user)
    unindex_user_data(user)


# courses


def delete_course_data(course):
    for iface in CONTAINER_INTERFACES:
        user_data = iface(course, None)
        if user_data is not None:
            user_data.clear()


def unindex_course_data(course):
    entry = ICourseCatalogEntry(course, None)
    site_name = get_resource_site_name(course)
    if entry is not None and site_name:
        catalog = get_submission_catalog()
        query = {IX_COURSE: {'any_of': (entry.ntiid,)},
                 IX_SITE: {'any_of': (site_name,)}}
        for uid in catalog.apply(query) or ():
            catalog.unindex_doc(uid)


@component.adapter(ICourseInstance, IIntIdRemovedEvent)
def on_course_instance_removed(course, unused_event):
    delete_course_data(course)
    unindex_course_data(course)


@component.adapter(IQuestion, IQuestionMovedEvent)
def on_question_moved(question, event):
    # We should only be moving questions within a question set.
    ntiid = getattr(question, 'ntiid', None)
    if ntiid:
        record_transaction(question, principal=event.principal,
                           type_=TRX_QUESTION_MOVE_TYPE)


@component.adapter(ICourseInstance, ICourseBundleUpdatedEvent)
def update_assessments_on_course_bundle_update(course, unused_event):
    """
    The course packages have been updated. Re-index any assessment
    items in our ICourseInstance packages.
    """
    index_course_package_assessments(course)
