#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import time

from pyramid.interfaces import IRequest

import six

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from zope.container.contained import Contained

from zope.container.ordered import OrderedContainer

from zope.location.interfaces import LocationError

from zope.location.location import locate

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.interfaces import ICourseAssignmentAttemptMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItemContainer

from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.assessment.interfaces import IQAssessment

from nti.containers.containers import CheckingLastModifiedBTreeContainer
from nti.containers.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization import ACT_CREATE
from nti.dataserver.authorization import ACT_UPDATE
from nti.dataserver.authorization import ROLE_ADMIN

from nti.dataserver.interfaces import IACLProvider

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.users.users import User

from nti.dublincore.datastructures import PersistentCreatedModDateTrackingObject

from nti.externalization.datastructures import InterfaceObjectIO

from nti.externalization.interfaces import IInternalObjectUpdater
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.oids import to_external_ntiid_oid

from nti.property.property import alias

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable

from nti.wref.interfaces import IWeakRef

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


@interface.implementer(ICourseAssignmentAttemptMetadata)
class CourseAssignmentAttemptMetadata(CaseInsensitiveCheckingLastModifiedBTreeContainer):
    """
    Implementation of the course assignment attempt metadata for all users in a course.
    """

    def clear(self):
        if len(self) == 0:
            return
        for key, value in list(self.items()):
            value.clear()
            del self[key]


@interface.implementer(IUsersCourseAssignmentAttemptMetadata)
class UsersCourseAssignmentAttemptMetadata(CheckingLastModifiedBTreeContainer,
                                           Contained,
                                           SchemaConfigured):

    __external_can_create__ = False

    _owner_ref = None

    def _get_owner(self):
        return self._owner_ref() if self._owner_ref else None

    def _set_owner(self, owner):
        self._owner_ref = IWeakRef(owner)
    owner = property(_get_owner, _set_owner)

    #: A non-interface attribute for convenience (acls)
    creator = alias('owner')

    @property
    def Items(self):
        return dict(self)

    def get_or_create(self, assignmentId, start_time=None):
        # FIXME
        if assignmentId not in self:
            start_time = float(start_time) if start_time is not None else start_time
            result = UsersCourseAssignmentAttemptMetadataItemContainer()
            self.append(assignmentId, result)
        else:
            result = self[assignmentId]
        return result
    getOrCreate = get_or_create

    def append(self, assignmentId, item):
        if item.__parent__ is not None:
            raise ValueError("Object already with a parent")
        self[assignmentId] = item
        return item

    def remove(self, assignmentId, event=False):
        if assignmentId not in self:
            return
        item = self[assignmentId]
        if event:
            del self[assignmentId]
        else:
            self._delitemf(assignmentId, event=False)
            locate(item, None, None)
            self.updateLastMod()

    def __conform__(self, iface):
        if IUser.isOrExtends(iface):
            return self.owner
        if ICourseInstance.isOrExtends(iface):
            return self.__parent__

    @property
    def __acl__(self):
        creator = self.creator
        aces = [ace_allowing(creator, ACT_READ, type(self)),
                ace_allowing(creator, ACT_CREATE, type(self))]
        aces.append(ACE_DENY_ALL)
        return acl_from_aces(aces)


@interface.implementer(IUsersCourseAssignmentAttemptMetadataItemContainer)
class UsersCourseAssignmentAttemptMetadataItemContainer(PersistentCreatedModDateTrackingObject,
                                                        OrderedContainer,
                                                        Contained,
                                                        SchemaConfigured):

    createDirectFieldProperties(IUsersCourseAssignmentAttemptMetadataItemContainer)

    __external_can_create__ = False

    @property
    def Items(self):
        return dict(self)

    def reset(self, event=True):
        keys = list(self)
        for k in keys:
            if event:
                del self[k]  # pylint: disable=unsupported-delete-operation
            else:
                self._delitemf(k)
    clear = reset


@interface.implementer(IUsersCourseAssignmentAttemptMetadataItem,
                       IACLProvider)
class UsersCourseAssignmentAttemptMetadataItem(PersistentCreatedModDateTrackingObject,
                                               SchemaConfigured,
                                               Contained):

    createDirectFieldProperties(IUsersCourseAssignmentAttemptMetadataItem)

    __external_can_create__ = True

    @property
    def id(self):
        return to_external_ntiid_oid(self)

    def __conform__(self, iface):
        if IUser.isOrExtends(iface):
            # If the user is deleted, we will not be able to do this
            try:
                meta_container = self.__parent__
                user_meta = meta_container.__parent__
                return iface(user_meta, None) or iface(meta_container)
            except (AttributeError, TypeError):
                return None

    @property
    def creator(self):
        return IUser(self, None)

    @creator.setter
    def creator(self, nv):
        pass

    @property
    def assignmentId(self):
        return self.__parent__.__name__

    @property
    def __acl__(self):
        creator = self.creator
        aces = [ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, type(self)),
                ace_allowing(creator, ACT_READ, type(self)),
                ace_allowing(creator, ACT_CREATE, type(self)),
                ace_allowing(creator, ACT_UPDATE, type(self))]

        course = ICourseInstance(self, None)
        # pylint: disable=not-an-iterable
        for instructor in getattr(course, 'instructors', ()):  # already principals
            aces.append(ace_allowing(instructor, ALL_PERMISSIONS, type(self)))

        aces.append(ACE_DENY_ALL)
        result = acl_from_aces(aces)
        return result


@interface.implementer(IInternalObjectUpdater)
@component.adapter(IUsersCourseAssignmentAttemptMetadataItem)
class _UsersCourseAssignmentAttemptMetadataItemUpdater(object):

    __slots__ = ('item',)

    def __init__(self, item):
        self.item = item

    def updateFromExternalObject(self, parsed, *args, **kwargs):
        # TODO: Do we need this?
        start_time = parsed.get('StartTime', None)
        if self.item.StartTime is None:
            if isinstance(start_time, six.string_types):
                parsed['StartTime'] = float(start_time)
        else:
            parsed.pop('StartTime', None)

        result = InterfaceObjectIO(
                    self.item,
                    IUsersCourseAssignmentAttemptMetadataItem).updateFromExternalObject(parsed, *args, **kwargs)
        return result


@component.adapter(ICourseInstance)
@interface.implementer(ICourseAssignmentAttemptMetadata)
def _metadata_for_course(course, create=True):
    # FIXME add to connection like in other places
    result = None
    annotations = IAnnotations(course)
    try:
        KEY = u'AssignmentMetadata'
        result = annotations[KEY]
    except KeyError:
        if create:
            result = CourseAssignmentAttemptMetadata()
            annotations[KEY] = result
            result.__name__ = KEY
            result.__parent__ = course
    return result


@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseAssignmentAttemptMetadata)
def _metadata_attempts_for_user_in_course(course, user, create=True):
    result = None
    container = _metadata_for_course(course)
    try:
        result = container[user.username]
    except KeyError:
        if create:
            result = UsersCourseAssignmentAttemptMetadata()
            result.owner = user
            container[user.username] = result
    return result


def _metadata_attempt_container_for_course_path_adapter(course, unused_request):
    return _metadata_for_course(course)


def _metadata_attempt_container_for_courseenrollment_path_adapter(enrollment, unused_request):
    return _metadata_for_course(ICourseInstance(enrollment))


@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentAttemptMetadataItem)
def _course_from_metadata_attempt_item_lineage(item):
    return course_from_context_lineage(item, validate=True)


@component.adapter(ICourseAssignmentAttemptMetadata, IRequest)
class _CourseMetadataAttemptContainerTraversable(ContainerAdapterTraversable):

    def traverse(self, key, remaining_path):
        try:
            return super(_CourseMetadataAttemptContainerTraversable, self).traverse(key, remaining_path)
        except LocationError:
            user = User.get_user(key)
            if user is not None:
                return _metadata_attempts_for_user_in_course(self.context.__parent__, user)
            raise


@component.adapter(IUsersCourseAssignmentAttemptMetadata, IRequest)
class _UsersCourseMetadataAttemptTraversable(ContainerAdapterTraversable):

    def traverse(self, key, unused_remaining_path):
        # FIXME is this right?
        assesment = component.queryUtility(IQAssessment, name=key)
        if assesment is not None:
            return assesment
        raise LocationError(self.context, key)


@component.adapter(ICourseInstance, IObjectAddedEvent)
def _attempt_meta_on_course_added(course, unused_event):
    _metadata_for_course(course)


@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectAddedEvent)
def _attempt_on_assignment_history_item_added(item, unused_event):
    user = IUser(item, None)
    course = find_interface(item, ICourseInstance, strict=False)
    assignment_metadata = component.queryMultiAdapter((course, user),
                                                      IUsersCourseAssignmentAttemptMetadata)
    if assignment_metadata is not None:
        # FIXME: We should already have an attempt here
        # Store weakref to item here
        meta_item = assignment_metadata.get_or_create(item.assignmentId, time.time())
        meta_item.Duration = time.time() - meta_item.StartTime
        meta_item.updateLastMod()


@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectRemovedEvent)
def _attempt_on_assignment_history_item_deleted(item, unused_event):
    """
    On reset, clear the attempt metadata associated with the given item
    """
    user = IUser(item, None)
    course = find_interface(item, ICourseInstance, strict=False)
    assignment_metadata = component.queryMultiAdapter((course, user),
                                                      IUsersCourseAssignmentAttemptMetadata)
    if assignment_metadata is not None:
        for attempt_meta in assignment_metadata.values():
            if attempt_meta.HistoryItem == item:
                del assignment_metadata[attempt_meta.__name__]


@component.adapter(IUsersCourseAssignmentHistoryItem)
@interface.implementer(IUsersCourseAssignmentAttemptMetadataItem)
def _assignment_history_item_to_metadata_attempt(item):
    """
    Find the attempt metadata associated with this hitory item.
    """
    user = IUser(item, None)
    course = find_interface(item, ICourseInstance, strict=False)
    assignment_metadata = component.queryMultiAdapter((course, user),
                                                      IUsersCourseAssignmentAttemptMetadata)
    if assignment_metadata is not None:
        for attempt_meta in assignment_metadata.values():
            if attempt_meta.HistoryItem == item:
                return attempt_meta

# ----------------------------------------


@interface.implementer(IUsersCourseAssignmentMetadataContainer)
class UsersCourseAssignmentMetadataContainer(CaseInsensitiveCheckingLastModifiedBTreeContainer):
    """
    Implementation of the course assignment metadata for all users in a course.
    """

    def clear(self):
        if len(self) == 0:
            return
        for key, value in list(self.items()):
            value.clear()
            del self[key]


@interface.implementer(IUsersCourseAssignmentMetadata)
class UsersCourseAssignmentMetadata(CheckingLastModifiedBTreeContainer):

    __external_can_create__ = False

    _owner_ref = None

    def _get_owner(self):
        return self._owner_ref() if self._owner_ref else None

    def _set_owner(self, owner):
        self._owner_ref = IWeakRef(owner)
    owner = property(_get_owner, _set_owner)

    #: A non-interface attribute for convenience (acls)
    creator = alias('owner')

    @property
    def Items(self):
        return dict(self)

    def get_or_create(self, assignmentId, start_time=None):
        if assignmentId not in self:
            start_time = float(start_time) if start_time is not None else start_time
            result = UsersCourseAssignmentMetadataItem(StartTime=start_time)
            self.append(assignmentId, result)
        else:
            result = self[assignmentId]
        return result
    getOrCreate = get_or_create

    def append(self, assignmentId, item):
        if item.__parent__ is not None:
            raise ValueError("Object already parented")
        self[assignmentId] = item
        return item

    def remove(self, assignmentId, event=False):
        if assignmentId not in self:
            return
        item = self[assignmentId]
        if event:
            del self[assignmentId]
        else:
            self._delitemf(assignmentId, event=False)
            locate(item, None, None)
            self.updateLastMod()

    def __conform__(self, iface):
        if IUser.isOrExtends(iface):
            return self.owner
        if ICourseInstance.isOrExtends(iface):
            return self.__parent__

    @property
    def __acl__(self):
        creator = self.creator
        aces = [ace_allowing(creator, ACT_READ, type(self)),
                ace_allowing(creator, ACT_CREATE, type(self))]
        aces.append(ACE_DENY_ALL)
        return acl_from_aces(aces)


@interface.implementer(IUsersCourseAssignmentMetadataItem,
                       IACLProvider)
class UsersCourseAssignmentMetadataItem(PersistentCreatedModDateTrackingObject,
                                        SchemaConfigured,
                                        Contained):

    createDirectFieldProperties(IUsersCourseAssignmentMetadataItem)

    __external_can_create__ = True

    @property
    def id(self):
        return to_external_ntiid_oid(self)

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
    def assignmentId(self):
        return self.__name__

    @property
    def __acl__(self):
        creator = self.creator
        aces = [ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, type(self)),
                ace_allowing(creator, ACT_READ, type(self)),
                ace_allowing(creator, ACT_CREATE, type(self)),
                ace_allowing(creator, ACT_UPDATE, type(self))]

        course = ICourseInstance(self, None)
        # pylint: disable=not-an-iterable
        for instructor in getattr(course, 'instructors', ()):  # already principals
            aces.append(ace_allowing(instructor, ALL_PERMISSIONS, type(self)))

        aces.append(ACE_DENY_ALL)
        result = acl_from_aces(aces)
        return result


@interface.implementer(IInternalObjectUpdater)
@component.adapter(IUsersCourseAssignmentMetadataItem)
class _UsersCourseAssignmentMetadataItemUpdater(object):

    __slots__ = ('item',)

    def __init__(self, item):
        self.item = item

    def updateFromExternalObject(self, parsed, *args, **kwargs):
        start_time = parsed.get('StartTime', None)
        if self.item.StartTime is None:
            if isinstance(start_time, six.string_types):
                parsed['StartTime'] = float(start_time)
        else:
            parsed.pop('StartTime', None)

        result = InterfaceObjectIO(
                    self.item,
                    IUsersCourseAssignmentMetadataItem).updateFromExternalObject(parsed, *args, **kwargs)
        return result


@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseAssignmentMetadataContainer)
def _metadatacontainer_for_course(course, create=True):
    result = None
    annotations = IAnnotations(course)
    try:
        KEY = u'AssignmentMetadata'
        result = annotations[KEY]
    except KeyError:
        if create:
            result = UsersCourseAssignmentMetadataContainer()
            annotations[KEY] = result
            result.__name__ = KEY
            result.__parent__ = course
    return result


@component.adapter(ICourseInstance, IUser)
@interface.implementer(IUsersCourseAssignmentMetadata)
def _metadata_for_user_in_course(course, user, create=True):
    result = None
    container = _metadatacontainer_for_course(course)
    try:
        result = container[user.username]
    except KeyError:
        if create:
            result = UsersCourseAssignmentMetadata()
            result.owner = user
            container[user.username] = result
    return result


def _metadatacontainer_for_course_path_adapter(course, unused_request):
    return _metadatacontainer_for_course(course)


def _metadatacontainer_for_courseenrollment_path_adapter(enrollment, unused_request):
    return _metadatacontainer_for_course(ICourseInstance(enrollment))


@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentMetadataItem)
def _course_from_metadataitem_lineage(item):
    return course_from_context_lineage(item, validate=True)


@component.adapter(IUsersCourseAssignmentMetadataContainer, IRequest)
class _UsersCourseMetadataContainerTraversable(ContainerAdapterTraversable):

    def traverse(self, key, remaining_path):
        try:
            return super(_UsersCourseMetadataContainerTraversable, self).traverse(key, remaining_path)
        except LocationError:
            user = User.get_user(key)
            if user is not None:
                return _metadata_for_user_in_course(self.context.__parent__, user)
            raise


@component.adapter(IUsersCourseAssignmentMetadata, IRequest)
class _UsersCourseMetadataTraversable(ContainerAdapterTraversable):

    def traverse(self, key, unused_remaining_path):
        assesment = component.queryUtility(IQAssessment, name=key)
        if assesment is not None:
            return assesment
        raise LocationError(self.context, key)


@component.adapter(ICourseInstance, IObjectAddedEvent)
def _on_course_added(course, unused_event):
    _metadatacontainer_for_course(course)


@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectAddedEvent)
def _on_assignment_history_item_added(item, unused_event):
    user = IUser(item, None)
    course = find_interface(item, ICourseInstance, strict=False)
    assignment_metadata = component.queryMultiAdapter((course, user),
                                                      IUsersCourseAssignmentMetadata)
    if assignment_metadata is not None:
        meta_item = assignment_metadata.get_or_create(
            item.assignmentId, time.time()
        )
        meta_item.Duration = time.time() - meta_item.StartTime
        meta_item.updateLastMod()


@component.adapter(IUsersCourseAssignmentHistoryItem, IObjectRemovedEvent)
def _on_assignment_history_item_deleted(item, unused_event):
    user = IUser(item, None)
    course = find_interface(item, ICourseInstance, strict=False)
    assignment_metadata = component.queryMultiAdapter((course, user),
                                                      IUsersCourseAssignmentMetadata)
    if assignment_metadata is not None:
        assignment_metadata.remove(item.assignmentId)


@component.adapter(IUsersCourseAssignmentHistoryItem)
@interface.implementer(IUsersCourseAssignmentMetadataItem)
def _assignment_history_item_2_metadata(item):
    user = IUser(item, None)
    course = find_interface(item, ICourseInstance, strict=False)
    metadata = component.queryMultiAdapter((course, user),
                                           IUsersCourseAssignmentMetadata)
    try:
        result = metadata[item.assignmentId] if metadata else None
    except KeyError:
        result = None
    return result
