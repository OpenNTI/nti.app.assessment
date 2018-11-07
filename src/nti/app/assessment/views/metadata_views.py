#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import time

from zope import interface
from zope import lifecycleevent

from zope.cachedescriptors.property import Lazy

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.evaluations import get_max_time_allowed
from nti.app.assessment.common.evaluations import get_course_from_evaluation

from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItemContainer

from nti.app.assessment.metadata import UsersCourseAssignmentAttemptMetadataItem

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views import get_ds2

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.renderers.interfaces import INoHrefInResponse

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid

logger = __import__('logging').getLogger(__name__)


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentAttemptMetadataItemContainer,
             renderer='rest',
             request_method='POST',
             permission=nauth.ACT_READ,
             name="Commence")
class AssignmentSubmissionStartPostView(AbstractAuthenticatedView):
    """
    The `start` of an assignment (timed or regular). This will create a
    :class:`IUsersCourseAssignmentAttemptMetadataItem` object it and
    store it in our :class:`IUsersCourseAssignmentAttemptMetadataItemContainer`.
    """

    @Lazy
    def assignment(self):
        return find_object_with_ntiid(self.context.__name__)

    def _validate(self):
        creator = self.remoteUser
        if not creator:
            raise hexc.HTTPForbidden(_(u"Must be Authenticated."))
        course = get_course_from_request(self.request)
        if course is None:
            course = get_course_from_evaluation(self.assignment,
                                                creator,
                                                exc=False)
        if course is None:
            raise hexc.HTTPForbidden(_(u"Must be enrolled in a course."))
        return creator, course

    def _process(self, item):
        lifecycleevent.created(item)
        self.request.response.status_int = 201
        item.containerId = self.context.__name__
        result = to_external_object(item)
        result['href'] = "/%s/Objects/%s" % (get_ds2(self.request),
                                             to_external_ntiid_oid(item))
        interface.alsoProvides(result, INoHrefInResponse)

        return result

    def __call__(self):
        # TODO: do we need to validate the size of the container?
        # I dont think so.
        self._validate()
        item = UsersCourseAssignmentAttemptMetadataItem()
        self.context.add_attempt(item)
        self._process(item)
        if not item.StartTime:
            item.StartTime = time.time()
        # FIXME: need seed
        # Must return assignment here, since the new metadata item may
        # drive randomization.
        return self.assignment


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentAttemptMetadataItemContainer,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ)
class AssignmentSubmissionMetadataGetView(AbstractAuthenticatedView):
    """
    Return the metadata item container for this user, course and assignment.
    """

    @Lazy
    def assignment(self):
        return find_object_with_ntiid(self.context.__name__)

    @Lazy
    def course(self):
        course = get_course_from_request(self.request)
        if course is None:
            evaluation = find_object_with_ntiid(self.context.__name__)
            course = get_course_from_evaluation(evaluation,
                                                self.remoteUser,
                                                exc=False)
        return course

    def _do_call(self):
        creator = self.remoteUser
        if not creator:
            raise hexc.HTTPForbidden(_(u"Must be Authenticated."))

        if self.course is None:
            raise hexc.HTTPForbidden(_(u"Must be enrolled in a course."))
        return self.context

    def __call__(self):
        return self._do_call()


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentAttemptMetadataItem,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="StartTime")
class AssignmentSubmissionStartGetView(AssignmentSubmissionMetadataGetView):
    """
    Return the :class:`IUsersCourseAssignmentAttemptMetadataItem` StartTime.
    """

    def __call__(self):
        try:
            self._do_call()
            result = LocatedExternalDict({'StartTime':
                                          self.context.StartTime})
            return result
        except KeyError:
            return hexc.HTTPNotFound()


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentAttemptMetadataItem,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="TimeRemaining")
class MetadataItemTimeRemainingGetView(AssignmentSubmissionMetadataGetView):
    """
    Return the time remaining in seconds until this `IQTimedAssignment` is
    due. We may return negative numbers to indicate past due status.
    """

    @Lazy
    def assignment(self):
        return find_object_with_ntiid(self.context.__parent__.__name__)

    def _get_time_remaining(self, metadata_item):
        # We return None if the assignment is not yet started.
        result = None
        if metadata_item.StartTime:
            max_time_allowed = get_max_time_allowed(self.assignment, self.course)
            if max_time_allowed:
                now = time.time()
                # Both in seconds
                end_point = metadata_item.StartTime + max_time_allowed
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
             context=IUsersCourseAssignmentAttemptMetadataItem,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="HistoryItem")
class MetadataItemHistoryItemGetView(AssignmentSubmissionMetadataGetView):
    """
    Return the history item associated with this metadata attempt item.
    """

    def __call__(self):
        return self.context.HistoryItem


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentAttemptMetadataItem,
             renderer='rest',
             permission=nauth.ACT_NTI_ADMIN,
             request_method='PUT')
class AssignmentMetadataItemPutView(UGDPutView):
    """
    NT Admins can edit metadata attempt items.
    """


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentAttemptMetadataItem,
             renderer='rest',
             permission=nauth.ACT_NTI_ADMIN,
             request_method='DELETE')
class AssignmentMetadataItemDeleteView(UGDDeleteView):
    """
    NT Admins can delete metadata attempt items.
    """

    def _do_delete_object(self, theObject):
        del theObject.__parent__[theObject.__name__]
        return theObject
