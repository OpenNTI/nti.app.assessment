#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from pyramid.interfaces import IRequest

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from zope.cachedescriptors.property import readproperty

from zope.container.contained import Contained

from zope.lifecycleevent.interfaces import IObjectAddedEvent

from zope.location.interfaces import ISublocations
from zope.location.interfaces import LocationError

from nti.app.assessment._submission import set_inquiry_submission_lineage

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.common.inquiries import get_course_inquiries

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import ICourseInquiryCatalog
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import ICourseAggregatedInquiries
from nti.app.assessment.interfaces import IUsersCourseInquiryItemResponse

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAggregatedSurvey

from nti.containers.containers import CheckingLastModifiedBTreeContainer
from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.authorization import ACT_READ

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS
from nti.dataserver.interfaces import EVERYONE_USER_NAME

from nti.dataserver.users.users import User

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.externalization.interfaces import StandardExternalFields

from nti.property.property import alias

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.traversal.traversal import ContainerAdapterTraversable

from nti.wref.interfaces import IWeakRef

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IUsersCourseInquiries)
class UsersCourseInquiries(CaseInsensitiveCheckingLastModifiedBTreeContainer):
    """
    Implementation of the course inquirys for all users in a course.
    """

    def clear(self):
        if len(self) == 0:
            return
        for key, value in list(self.items()):
            value.clear()
            del self[key]
        
UsersCourseSurveys = UsersCourseInquiries  # BWC


@interface.implementer(IUsersCourseInquiry)
class UsersCourseInquiry(CheckingLastModifiedBTreeContainer):

    __external_can_create__ = False

    #: An :class:`.IWeakRef` to the owning user
    _owner_ref = None

    def _get_owner(self):
        return self._owner_ref() if self._owner_ref else None

    def _set_owner(self, owner):
        self._owner_ref = IWeakRef(owner)
    owner = property(_get_owner, _set_owner)

    creator = alias('owner')

    @property
    def Items(self):
        return dict(self)

    def recordSubmission(self, submission):
        if submission.__parent__ is not None:
            raise ValueError("Objects already parented")

        item = UsersCourseInquiryItem(Submission=submission)
        submission.__parent__ = item
        set_inquiry_submission_lineage(submission)

        self[submission.inquiryId] = item
        return item

    def removeSubmission(self, submission):
        inquiryId = getattr(submission, 'inquiryId', str(submission))
        if inquiryId not in self:
            return
        del self[inquiryId]

    def __conform__(self, iface):
        if IUser.isOrExtends(iface):
            return self.owner

        if ICourseInstance.isOrExtends(iface):
            return self.__parent__

    @property
    def __acl__(self):
        course = ICourseInstance(self, None)
        instructors = getattr(course, 'instructors', ())  # already principals
        aces = [ace_allowing(self.owner, ACT_READ, type(self))]
        # pylint: disable=not-an-iterable
        for instructor in instructors or ():
            aces.append(ace_allowing(instructor, ALL_PERMISSIONS, type(self)))
        aces.append(ACE_DENY_ALL)
        return acl_from_aces(aces)


@interface.implementer(IUsersCourseInquiryItem,
                       IACLProvider,
                       ISublocations)
class UsersCourseInquiryItem(PersistentCreatedModDateTrackingObject,
                             Contained,
                             SchemaConfigured):
    createDirectFieldProperties(IUsersCourseInquiryItem)

    __external_can_create__ = False

    def __conform__(self, iface):
        if IUser.isOrExtends(iface):
            try:
                return iface(self.__parent__)
            except (AttributeError, TypeError):
                return None

    @property
    def creator(self):
        return IUser(self, None)

    @creator.setter
    def creator(self, nv):
        pass

    @property
    def inquiryId(self):
        return self.__name__

    @readproperty
    def Inquiry(self):
        result = component.queryUtility(IQInquiry, name=self.__name__ or '')
        return result

    @property
    def __acl__(self):
        course = ICourseInstance(self, None)
        instructors = getattr(course, 'instructors', ())  # already principals
        aces = [ace_allowing(self.creator, ACT_READ, type(self))]
        # pylint: disable=not-an-iterable
        for instructor in instructors or ():
            aces.append(ace_allowing(instructor, ALL_PERMISSIONS, type(self)))
        aces.append(ACE_DENY_ALL)
        return acl_from_aces(aces)

    def sublocations(self):
        if self.Submission is not None:
            yield self.Submission


@interface.implementer(IUsersCourseInquiryItemResponse)
class UsersCourseInquiryItemResponse(SchemaConfigured):
    createDirectFieldProperties(IUsersCourseInquiryItemResponse)


@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseInquiries)
def _inquiries_for_course(course, create=True):
    result = None
    annotations = IAnnotations(course)
    try:
        KEY = u'Inquiries'
        result = annotations[KEY]
    except KeyError:
        if create:
            result = UsersCourseInquiries()
            annotations[KEY] = result
            result.__name__ = KEY
            result.__parent__ = course
    return result


@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseInquiry)
def _inquiry_for_user_in_course(course, user, create=True):
    result = None
    inquiries = _inquiries_for_course(course)
    try:
        result = inquiries[user.username]
    except KeyError:
        if create:
            result = UsersCourseInquiry()
            result.owner = user
            inquiries[user.username] = result
    return result


def _inquiries_for_course_path_adapter(course, unused_request):
    return _inquiries_for_course(course)


def _inquiries_for_courseenrollment_path_adapter(enrollment, unused_request):
    return _inquiries_for_course(ICourseInstance(enrollment))


@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseInquiryItem)
def _course_from_inquiryitem_lineage(item):
    return course_from_context_lineage(item)


@component.adapter(IUsersCourseInquiries, IRequest)
class _UsersCourseInquiriesTraversable(ContainerAdapterTraversable):

    def traverse(self, key, remaining_path):
        try:
            return super(_UsersCourseInquiriesTraversable, self).traverse(key, remaining_path)
        except LocationError:
            user = User.get_user(key)
            if user is not None:
                return _inquiry_for_user_in_course(self.context.__parent__, user)
            raise


@component.adapter(IUsersCourseInquiry, IRequest)
class _UsersCourseInquiryTraversable(ContainerAdapterTraversable):

    def traverse(self, key, unused_remaining_path):
        assesment = component.queryUtility(IQInquiry, name=key)
        if assesment is not None:
            return assesment
        raise LocationError(self.context, key)


@interface.implementer(ICourseInquiryCatalog)
@component.adapter(ICourseInstance)
class _DefaultCourseInquiryCatalog(object):

    def __init__(self, context):
        self.context = context

    def iter_inquiries(self):
        result = get_course_inquiries(self.context)
        return result


@interface.implementer(ICourseAggregatedInquiries)
class CourseAggregatedSurveys(CheckingLastModifiedBTreeContainer):

    __external_can_create__ = False

    def __conform__(self, iface):
        if ICourseInstance.isOrExtends(iface):
            return self.__parent__

    @property
    def __acl__(self):
        course = ICourseInstance(self, None)
        instructors = getattr(course, 'instructors', ()) # already principals
        # pylint: disable=not-an-iterable
        aces = [ace_allowing(i, ALL_PERMISSIONS, type(self))
                for i in instructors or ()]
        aces.append(ace_allowing(EVERYONE_USER_NAME, ACT_READ))
        return acl_from_aces(aces)


@component.adapter(ICourseInstance)
@interface.implementer(ICourseAggregatedInquiries)
def _aggreated_inquiries_for_course(course):
    annotations = IAnnotations(course)
    try:
        KEY = u'AggregatedInquiries'
        result = annotations[KEY]
    except KeyError:
        result = CourseAggregatedSurveys()
        annotations[KEY] = result
        result.__name__ = KEY
        result.__parent__ = course
    return result


def _aggreated_inquiries_for_course_path_adapter(course, unused_request):
    return _aggreated_inquiries_for_course(course)


def _aggreated_inquiries_for_courseenrollment_path_adapter(enrollment, unused_request):
    return _aggreated_inquiries_for_course(ICourseInstance(enrollment))


@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, unused_event):
    _inquiries_for_course(course)


@component.adapter(IUsersCourseInquiryItem, IObjectAddedEvent)
def _on_course_inquiry_item_added(unused_item, unused_event):
    pass


def aggregate_survey_submission(storage, submission):
    # pylint: disable=not-an-iterable
    aggregated_inquiry = IQAggregatedSurvey(submission)
    for aggregated_poll in aggregated_inquiry.questions:
        pollId = aggregated_poll.pollId
        if pollId not in storage:
            storage[pollId] = aggregated_poll
        else:
            stored = storage[pollId]
            stored += aggregated_poll
