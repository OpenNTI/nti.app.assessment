#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=abstract-method
from zope import component

from zope.location.interfaces import ILocationInfo

from pyramid.threadlocal import get_current_request

from nti.app.assessment.common.evaluations import get_course_from_evaluation

from nti.app.assessment.interfaces import ACT_VIEW_SOLUTIONS

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import get_package_from_request

from nti.app.authentication import get_remote_user

from nti.app.products.courseware.utils import PreviewCourseAccessPredicateDecorator

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.contentlibrary.externalization import root_url_of_unit

from nti.contentlibrary.interfaces import IContentPackageLibrary
from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.dataserver.users import User

from nti.externalization.singleton import Singleton

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


class _AbstractTraversableLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, unused_result):
        # We only do this if we can create the traversal path to this object;
        # many times the CourseInstanceEnrollments aren't fully traversable
        # (specifically, for the course roster)
        if self._is_authenticated:
            if context.__parent__ is None:
                return False  # Short circuit
            try:
                loc_info = ILocationInfo(context)
                # pylint: disable=too-many-function-args
                loc_info.getParents()
            except TypeError:
                return False
            else:
                return True
    _is_traversable = _predicate


class AbstractAssessmentDecoratorPredicate(PreviewCourseAccessPredicateDecorator,
                                           _AbstractTraversableLinkDecorator):
    """
    Only decorate assessment items if we are preview-safe, traversable and authenticated.
    """

    def _predicate(self, context, result):
        return super(AbstractAssessmentDecoratorPredicate, self)._predicate(context, result) \
               and self._is_traversable(context, result)


def _get_course_from_evaluation(evaluation, user=None, catalog=None, request=None):
    result = get_course_from_request(request)
    if result is None:
        result = get_course_from_evaluation(evaluation=evaluation,
                                            user=user,
                                            catalog=catalog)
    return result


def _get_package_from_evaluation(evaluation, request=None):
    result = get_package_from_request(request)
    if result is None:
        result = find_interface(evaluation, IEditableContentPackage, strict=False)
    return result


def _root_url(ntiid):
    library = component.queryUtility(IContentPackageLibrary)
    if ntiid and library is not None:
        paths = library.pathToNTIID(ntiid)
        package = paths[0] if paths else None
        try:
            return root_url_of_unit(package) if package is not None else None
        except Exception:  # pylint: disable=broad-except
            pass
    return None


class AbstractSolutionStrippingDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _get_course(self, context, user_id, request):
        remote_user = User.get_user(user_id)
        course = _get_course_from_evaluation(context, remote_user,
                                             request=request)
        return course

    @property
    def _is_instructor_cache(self):
        if not hasattr(self.request, '_v_is_instructor'):
            self.request._v_is_instructor = dict()

        return self.request._v_is_instructor

    def is_instructor(self, course, request):
        cached_result = self._is_instructor_cache.get(course.ntiid)
        if cached_result is not None:
            return cached_result

        result = (has_permission(ACT_VIEW_SOLUTIONS, course, request)
                  or has_permission(ACT_CONTENT_EDIT, course, request))

        self._is_instructor_cache[course.ntiid] = result

        return result

    def _predicate(self, context, _unused_result):
        auth_userid = self.authenticated_userid
        course = self._get_course(context, auth_userid, self.request)
        return (not bool(auth_userid)
                or course is None
                or not self.is_instructor(course, self.request))
