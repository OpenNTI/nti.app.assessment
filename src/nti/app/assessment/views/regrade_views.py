#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from requests.structures import CaseInsensitiveDict

from zope import component

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _
from nti.app.assessment import VIEW_REGRADE_EVALUATION

from nti.app.assessment.common.evaluations import get_evaluation_courses

from nti.app.assessment.common.grading import regrade_evaluation

from nti.app.assessment.utils import get_course_from_request

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IGroupMember

from nti.dataserver.users.users import User


@view_config(context=IQuestion)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               name=VIEW_REGRADE_EVALUATION,
               permission=nauth.ACT_READ)
class RegradeEvaluationView(AbstractAuthenticatedView):

    @property
    def _admin_user(self):
        result = set()
        for _, adapter in component.getAdapters((self.remoteUser,), IGroupMember):
            result.update(adapter.groups)
        return nauth.ROLE_ADMIN in result

    def _get_instructor(self):
        params = CaseInsensitiveDict(self.request.params)
        username = params.get('user') \
                or params.get('username') \
                or params.get('instructor')
        result = User.get_user(username)
        if result is None:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"No instructor found."),
                                 'code': 'CannotFindInstructor',
                             },
                             None)
        return result

    def _get_courses(self, evaluation):
        result = get_course_from_request(self.request)
        if result is None:
            # If no course in request, get all courses for this assignment.
            result = get_evaluation_courses(evaluation)
        else:
            result = (result,)
        return result

    def _validate_regrade(self, course, user):
        # Only admins or instructors are able to make this call.
        # Otherwise, make sure the user param passed in is an
        # instructor.
        if (    not self._admin_user
            and not is_course_instructor(course, self.remoteUser)) \
            or not is_course_instructor(course, user):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot regrade evaluation."),
                                 'code': 'CannotRegradeEvaluation',
                             },
                             None)

    def __call__(self):
        user = self.remoteUser
        if self._admin_user:
            # We allow admin users to regrade as instructors.
            user = self._get_instructor()
        courses = self._get_courses(self.context)
        if not courses:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot find evaluation course."),
                                 'code': 'CannotFindEvaluationCourse',
                             },
                             None)
        for course in courses:
            self._validate_regrade(course, user)
            entry = ICourseCatalogEntry(course, None)
            entry_ntiid = getattr(entry, 'ntiid', '')
            logger.info('%s regrading %s (%s) (course=%s)',
                        user.username, self.context.ntiid,
                        self.remoteUser.username, entry_ntiid)
            # The grade object itself actually arbitrarily picks an
            # instructor as the creator.
            regrade_evaluation(self.context, course)
        return self.context
