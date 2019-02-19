#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import time
from itertools import chain
from datetime import datetime

from pyramid.httpexceptions import HTTPUnprocessableEntity

from pyramid.threadlocal import get_current_request

import simplejson

from zc.intid.interfaces import IAfterIdAddedEvent

from zope import component
from zope import lifecycleevent

from zope.container.interfaces import IContainer

from zope.event import notify

from zope.intid.interfaces import IIntIds
from zope.intid.interfaces import IIntIdRemovedEvent

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from zope.traversing.interfaces import IBeforeTraverseEvent

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.containers import index_course_package_assessments

from nti.app.assessment.common.evaluations import get_unit_assessments
from nti.app.assessment.common.evaluations import get_course_from_evaluation
from nti.app.assessment.common.evaluations import is_discussion_assignment_non_public

from nti.app.assessment.common.hostpolicy import get_resource_site_name

from nti.app.assessment.common.utils import get_available_for_submission_ending

from nti.app.assessment.index import IX_SITE
from nti.app.assessment.index import IX_COURSE
from nti.app.assessment.index import IX_CREATOR
from nti.app.assessment.index import get_submission_catalog

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepointItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem

from nti.app.externalization.error import raise_json_error

from nti.app.products.courseware.interfaces import ICourseInstanceActivity

from nti.assessment import ASSESSMENT_INTERFACES

from nti.assessment.interfaces import TRX_QUESTION_MOVE_TYPE

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQuestionMovedEvent
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQDiscussionAssignment

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IEditableContentPackage
from nti.contentlibrary.interfaces import IRenderableContentPackage

from nti.contenttypes.courses import get_enrollment_catalog

from nti.contenttypes.courses.index import IX_USERNAME

from nti.contenttypes.completion.interfaces import ICompletionContextProvider
from nti.contenttypes.completion.interfaces import UserProgressRemovedEvent
from nti.contenttypes.completion.interfaces import IUserProgressUpdatedEvent

from nti.contenttypes.completion.utils import update_completion

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseBundleUpdatedEvent

from nti.coremetadata.interfaces import IContainerContext
from nti.coremetadata.interfaces import UserProcessedContextsEvent

from nti.dataserver.interfaces import IUser

from nti.dataserver.users.interfaces import IWillDeleteEntityEvent

from nti.externalization.externalization import to_external_object

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid

from nti.publishing.interfaces import IPublishable
from nti.publishing.interfaces import IObjectPublishedEvent
from nti.publishing.interfaces import IObjectUnpublishedEvent

from nti.recorder.utils import record_transaction

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


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
    # pylint: disable=too-many-function-args
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
    # pylint: disable=too-many-function-args
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
                e.content_type = 'application/json'
                raise e


# users


CONTAINER_INTERFACES = (IUsersCourseInquiries,
                        IUsersCourseAssignmentHistories,
                        IUsersCourseAssignmentSavepoints,
                        IUsersCourseAssignmentMetadataContainer)


def delete_course_user_data(course, username):
    for iface in CONTAINER_INTERFACES:
        user_data = iface(course, None)
        if user_data is not None and username in user_data:
            container = user_data[username]
            if IContainer.providedBy(container):
                container.clear()
            del user_data[username]


def delete_user_data(user):
    username = user.username
    catalog = get_enrollment_catalog()
    intids = component.getUtility(IIntIds)
    query = {IX_USERNAME: {'any_of': (username,)}}
    for uid in catalog.apply(query) or ():
        context = intids.queryObject(uid)
        course = ICourseInstance(context, None)
        if course is not None:
            delete_course_user_data(course, username)


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


@component.adapter(IQDiscussionAssignment, IObjectModifiedEvent)
def on_discussion_assignment_updated(context, event=None):
    """
    We may set the public status of this assignment, but only if the topic
    we're pointing at changes.
    """
    external_value = getattr(event, 'external_value', {})
    if 'discussion_ntiid' in external_value:
        is_non_public = is_discussion_assignment_non_public(context)
        context.is_non_public = is_non_public


@component.adapter(IQDiscussionAssignment, IObjectAddedEvent)
def on_discussion_assignment_created(context, unused_event=None):
    is_non_public = is_discussion_assignment_non_public(context)
    context.is_non_public = is_non_public


@component.adapter(IQEditableEvaluation, IObjectPublishedEvent)
def on_evaluation_published(context, unused_event=None):
    unit = find_interface(context, IEditableContentPackage, strict=False)
    if unit is not None and not unit.is_published():
        raise_json_error(get_current_request(),
                         HTTPUnprocessableEntity,
                         {
                             'message': _(u"Cannot publish evaluation while reading is unpublished."),
                         },
                         None)


@component.adapter(IRenderableContentPackage, IObjectPublishedEvent)
def on_renderable_package_published(context, unused_event=None):
    evals = IQEvaluations(context, None)
    if evals:
        for item in evals.values():  # pylint: disable=too-many-function-args
            if IPublishable.providedBy(item):
                item.publish()


@component.adapter(IRenderableContentPackage, IObjectUnpublishedEvent)
def on_renderable_package_unpublished(context, unused_event=None):
    evals = IQEvaluations(context, None)
    if evals:
        for item in evals.values():  # pylint: disable=too-many-function-args
            if IPublishable.providedBy(item):
                item.unpublish()


@component.adapter(ICourseInstance, ICourseBundleUpdatedEvent)
def on_course_bundle_updated(unused_course, event):
    """
    Index the authored evals to update their containers data
    """
    packages = chain(event.added_packages or (),
                     event.removed_packages or ())
    for package in packages:
        if not IEditableContentPackage.providedBy(package):
            continue
        evals = IQEvaluations(package, None)
        if evals:
            # pylint: disable=too-many-function-args
            map(lifecycleevent.modified, evals.values())


@component.adapter(IQAssessedQuestionSet, IAfterIdAddedEvent)
def _self_assessment_progress(submission, unused_event):
    """
    On a self-assessment assessed, update completion state as needed.
    """
    # We'll have creator for self-assessments, but not for assignments,
    # which we throw away anyway.
    history_item = find_interface(submission,
                                  IUsersCourseAssignmentHistoryItem,
                                  strict=False)
    if history_item is None:
        question_set = find_object_with_ntiid(submission.questionSetId)
        # Seems like we should fail fast here too
        container_context = IContainerContext(submission, None)
        if container_context is not None:
            context_id = container_context.context_id
            context = find_object_with_ntiid(context_id)
            update_completion(question_set, submission.questionSetId,
                              submission.creator, context)


@component.adapter(IQSurveySubmission, IObjectAddedEvent)
def _survey_progress(submission, unused_event):
    """
    On a survey submission, update completion state as needed.
    """
    survey = find_object_with_ntiid(submission.surveyId)
    provider = ICompletionContextProvider(survey, None)
    context = provider() if provider else None
    if context is not None:
        update_completion(survey,
                          survey.ntiid,
                          submission.creator,
                          context)


@component.adapter(IQAssessedQuestionSet, IObjectRemovedEvent)
def _self_assessment_submission_deleted(submission, unused_event):
    history_item = find_interface(submission,
                                  IUsersCourseAssignmentHistoryItem,
                                  strict=False)
    if history_item is None:
        question_set = find_object_with_ntiid(submission.questionSetId)
        # Seems like we should fail fast here too
        container_context = IContainerContext(question_set, None)
        if container_context is not None:
            context_id = container_context.context_id
            context = find_object_with_ntiid(context_id)
            notify(UserProgressRemovedEvent(question_set,
                                            submission.creator,
                                            context))


@component.adapter(IQAssignment, IUserProgressUpdatedEvent)
def _assignment_progress(assignment, event):
    """
    On an assignment submission, update completion state as needed.
    """
    update_completion(assignment,
                      assignment.ntiid,
                      event.user,
                      event.context)


@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectRemovedEvent)
def _on_assignment_history_item_deleted(item, unused_event):
    course = ICourseInstance(item)
    notify(UserProgressRemovedEvent(item.Assignment,
                                    item.creator,
                                    course))


@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectAddedEvent)
def _on_assignment_history_item_added(item, unused_event):
    # None in tests
    course = ICourseInstance(item, None)
    if course is not None:
        request = get_current_request()
        contexts = (to_external_ntiid_oid(course),)
        notify(UserProcessedContextsEvent(item.creator, contexts,
                                          time.time(), request))


@component.adapter(IUsersCourseAssignmentAttemptMetadataItem, IBeforeTraverseEvent)
def meta_attempt_item_context_subscriber(meta_attempt_item, unused_event):
    """
    Store the meta attempt item in our request during traversal; this
    is useful when fetching history items or assignments in the context
    of a meta attempt item, giving us access to the randomization seed
    we need.
    """
    request = get_current_request()
    if request is not None:
        request.meta_attempt_item_traversal_context = meta_attempt_item


@component.adapter(IUsersCourseAssignmentHistoryItem, IBeforeTraverseEvent)
def history_item_context_subscriber(history_item, event):
    """
    Store the meta attempt item in our request during traversal; this
    is useful when fetching history items or assignments in the context
    of a meta attempt item, giving us access to the randomization seed
    we need.
    """
    meta = IUsersCourseAssignmentAttemptMetadataItem(history_item, None)
    if meta is not None:
        meta_attempt_item_context_subscriber(meta, event)
