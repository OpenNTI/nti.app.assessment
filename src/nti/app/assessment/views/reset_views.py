#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.cachedescriptors.property import Lazy

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_RESET_EVALUATION
from nti.app.assessment import VIEW_USER_RESET_EVALUATION

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import has_inquiry_submissions
from nti.app.assessment.common import delete_evaluation_metadata
from nti.app.assessment.common import delete_inquiry_submissions
from nti.app.assessment.common import get_course_from_evaluation
from nti.app.assessment.common import delete_evaluation_savepoints
from nti.app.assessment.common import delete_evaluation_submissions

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint

from nti.app.assessment.utils import get_course_from_request

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization import ACT_NTI_ADMIN

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


class EvaluationResetMixin(ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            result = super(EvaluationResetMixin, self).readInput(value)
            result = CaseInsensitiveDict(result)
        else:
            result = CaseInsensitiveDict(self.request.params)
        return result

    @Lazy
    def course(self):
        if IQEditableEvaluation.providedBy(self.context):
            result = find_interface(self.context, 
									ICourseInstance, 
									strict=False)
        else:
            result = get_course_from_request(self.request)
            if result is None:
                result = get_course_from_evaluation(self.context, 
													self.remoteUser)
        return result

    @Lazy
    def _can_delete_contained_data(self):
        return is_course_instructor(self.course, self.remoteUser) \
            or has_permission(ACT_NTI_ADMIN, self.course, self.request)


@view_config(context=IQPoll)
@view_config(context=IQSurvey)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               name=VIEW_RESET_EVALUATION,
               permission=ACT_READ)
class EvaluationResetView(AbstractAuthenticatedView,
                          EvaluationResetMixin):

    def _has_submissions(self, theObject):
        if IQInquiry.providedBy(theObject):
            result = has_inquiry_submissions(theObject, self.course)
        else:
            courses = get_courses(self.course)
            result = has_submissions(theObject, courses) \
                  or has_savepoints(theObject, courses)
        return result

    def _delete_contained_data(self, theObject):
        if IQInquiry.providedBy(theObject):
            delete_inquiry_submissions(theObject, self.course)
        else:
            delete_evaluation_metadata(theObject, self.course)
            delete_evaluation_savepoints(theObject, self.course)
            delete_evaluation_submissions(theObject, self.course)

    def __call__(self):
        if not self._can_delete_contained_data:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                'message': _(u"Cannot reset evaluation object."),
                                'code': 'CannotResetEvaluation',
                             },
                             None)
        elif self._has_submissions(self.context):
            self._delete_contained_data(self.context)
        self.context.update_version()
        return self.context


@view_config(context=IQPoll)
@view_config(context=IQSurvey)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               name=VIEW_USER_RESET_EVALUATION,
               permission=ACT_READ)
class UserEvaluationResetView(AbstractAuthenticatedView,
                              EvaluationResetMixin):

    def _delete_contained_data(self, course, theObject, usernames):
        result = set()
        ntiid = theObject.ntiid
        if IQInquiry.providedBy(theObject):
            container_interfaces = (IUsersCourseInquiry,)
        else:
            container_interfaces = (IUsersCourseAssignmentHistory,
                                    IUsersCourseAssignmentMetadata,
                                    IUsersCourseAssignmentSavepoint)
        # remove user data
        for username in usernames or ():
            user = User.get_user(username)
            if not IUser.providedBy(user):
                continue
            for provided in container_interfaces:
                container = component.queryMultiAdapter((course, user), 
                                                        provided)
                if container and ntiid in container:
                    del container[ntiid]
                    result.add(username)
        return sorted(result)

    def __call__(self):
        values = self.readInput()
        if not self._can_delete_contained_data:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                'message': _(u"Cannot reset evaluation object."),
                                'code': 'CannotResetEvaluation',
                             },
                             None)

        usernames = values.get('user') \
                 or values.get('users') \
                 or values.get('username') \
                 or values.get('usernames')
        if isinstance(usernames, six.string_types):
            usernames = usernames.split()
        if not usernames:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                'message': _(u"Must specify a username."),
                                'code': 'MustSpecifyUsername',
                             },
                             None)

        items = self._delete_contained_data(self.course, 
                                            self.context, 
                                            usernames)
        result = LocatedExternalDict()
        result[ITEMS] = items
        result[TOTAL] = result[ITEM_COUNT] = len(items)
        return result
