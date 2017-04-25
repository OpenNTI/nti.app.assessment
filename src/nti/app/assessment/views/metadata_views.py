#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.cachedescriptors.property import Lazy

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import get_max_time_allowed
from nti.app.assessment.common import get_course_from_evaluation

from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.app.assessment.metadata import UsersCourseAssignmentMetadataItem

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views import get_ds2

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.renderers.interfaces import INoHrefInResponse

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict

from nti.externalization.oids import to_external_ntiid_oid


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             request_method='POST',
             permission=nauth.ACT_READ,
             name="Metadata")
class AssignmentSubmissionMetataPostView(AbstractAuthenticatedView,
                                         ModeledContentUploadRequestUtilsMixin):

    _EXTRA_INPUT_ERRORS = ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + \
                          (AttributeError,)

    content_predicate = IUsersCourseAssignmentMetadataItem.providedBy

    def _validate(self):
        creator = self.remoteUser
        if not creator:
            raise hexc.HTTPForbidden(_("Must be Authenticated."))
        course = get_course_from_request(self.request)
        if course is None:
            course = get_course_from_evaluation(self.context, 
                                                creator, 
                                                exc=False)
        if course is None:
            raise hexc.HTTPForbidden(_("Must be enrolled in a course."))
        return creator, course

    def _process(self, creator=None, course=None, item=None):
        if creator is None or course is None:
            creator, course = self._validate()
        if item is None:
            item = self.readCreateUpdateContentObject(creator)
        lifecycleevent.created(item)

        self.request.response.status_int = 201

        assignmentId = self.context.ntiid
        metadata = component.getMultiAdapter((course, creator),
                                             IUsersCourseAssignmentMetadata)
        item.containerId = assignmentId
        result = recorded = metadata.append(assignmentId, item)

        result = to_external_object(result)
        result['href'] = "/%s/Objects/%s" % (get_ds2(self.request),
                                             to_external_ntiid_oid(recorded))
        interface.alsoProvides(result, INoHrefInResponse)

        return result

    def _do_call(self):
        return self._process()


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             request_method='POST',
             permission=nauth.ACT_READ,
             name="Commence")
class AssignmentSubmissionStartPostView(AssignmentSubmissionMetataPostView):

    def _do_call(self):
        creator, course = self._validate()
        container = component.getMultiAdapter((course, creator),
                                              IUsersCourseAssignmentMetadata)
        try:
            item = container[self.context.ntiid]
        except KeyError:
            item = UsersCourseAssignmentMetadataItem()
            self._process(creator=creator, course=course, item=item)
        if not item.StartTime:
            item.StartTime = time.time()
        # return assignment
        return self.context


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="Metadata")
class AssignmentSubmissionMetadataGetView(AbstractAuthenticatedView):

    @Lazy
    def course(self):
        course = get_course_from_request(self.request)
        if course is None:
            course = get_course_from_evaluation(self.context, 
                                                self.remoteUser, 
                                                exc=False)
        return course

    def _do_call(self):
        creator = self.remoteUser
        if not creator:
            raise hexc.HTTPForbidden(_("Must be Authenticated."))

        if self.course is None:
            raise hexc.HTTPForbidden(_("Must be enrolled in a course."))

        container = component.getMultiAdapter((self.course, creator),
                                              IUsersCourseAssignmentMetadata)

        result = container[self.context.ntiid]
        return result

    def __call__(self):
        try:
            result = self._do_call()
            return result
        except KeyError:
            return hexc.HTTPNotFound()


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="StartTime")
class AssignmentSubmissionStartGetView(AssignmentSubmissionMetadataGetView):

    def __call__(self):
        try:
            item = self._do_call()
            result = LocatedExternalDict({'StartTime': item.StartTime})
            return result
        except KeyError:
            return hexc.HTTPNotFound()


@view_config(route_name="objects.generic.traversal",
             context=IQTimedAssignment,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="TimeRemaining")
class AssignmentTimeRemainingGetView(AssignmentSubmissionMetadataGetView):
    """
    Return the time remaining in seconds until this `IQTimedAssignment` is
    due. We may return negative numbers to indicate past due status.
    """

    def _get_time_remaining(self, metadata):
        # We return None if the assignment is not yet started.
        result = None
        if metadata.StartTime:
            max_time_allowed = get_max_time_allowed(self.context, self.course)
            if max_time_allowed:
                now = time.time()
                # Both in seconds
                end_point = metadata.StartTime + max_time_allowed
                result = end_point - now
        return result

    def __call__(self):
        try:
            item = self._do_call()
            time_remaining = self._get_time_remaining(item)
            result = LocatedExternalDict({'TimeRemaining': time_remaining})
            return result
        except KeyError:
            return hexc.HTTPNotFound()


@view_config(route_name="objects.generic.traversal",
             renderer='rest',
             context=IUsersCourseAssignmentMetadataContainer,
             permission=nauth.ACT_READ,
             request_method='GET')
class AssignmentMetadataGetView(AbstractAuthenticatedView):
    """
    Students can view their assignment metadata  as ``path/to/course/AssignmentMetadata``
    """

    def __call__(self):
        container = self.request.context
        return container


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentMetadataItem,
             renderer='rest',
             permission=nauth.ACT_UPDATE,
             request_method='PUT')
class AssignmentMetadataItemPutView(UGDPutView):
    pass


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentMetadataItem,
             renderer='rest',
             permission=nauth.ACT_DELETE,
             request_method='DELETE')
class AssignmentMetadataItemDeleteView(UGDDeleteView):

    def _do_delete_object(self, theObject):
        del theObject.__parent__[theObject.__name__]
        return theObject
