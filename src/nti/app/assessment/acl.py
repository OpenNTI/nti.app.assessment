#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from nti.appserver.pyramid_authorization import get_cache_acl
from nti.appserver.pyramid_authorization import get_request_acl_cache

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_editors
from nti.contenttypes.courses.utils import content_unit_to_courses

from nti.dataserver.authorization import ACT_DELETE
from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_SITE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.interfaces import IACLProvider

from nti.traversal.traversal import find_interface


logger = __import__('logging').getLogger(__name__)


def get_evaluation_courses(context):
    course = find_interface(context, ICourseInstance, strict=False)
    if course is not None:  # editable evals
        result = (course,)
    else:  # legacy
        package = find_interface(context, IContentPackage, strict=False)
        if package is not None:
            result = content_unit_to_courses(package)
        else:
            result = ()
    return result


@component.adapter(IQEvaluation)
@interface.implementer(IACLProvider)
class EvaluationACLProvider(object):

    """
    Provides the basic ACL for an evaluation.
    """

    def __init__(self, context):
        self.context = context

    @property
    def __parent__(self):
        return self.context.__parent__

    @Lazy
    def __acl__(self):
        aces = [ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, type(self)),
                ace_allowing(ROLE_SITE_ADMIN, ALL_PERMISSIONS, type(self)),
                ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
        result = acl_from_aces(aces)
        # Extend with any course acls.
        acl_cache = get_request_acl_cache()
        courses = get_evaluation_courses(self.context)
        for course in courses or ():
            acl = get_cache_acl(course, acl_cache)
            result.extend(acl)
            if IQEditableEvaluation.providedBy(self.context):
                for editor in get_course_editors(course):
                    result.append(ace_allowing(editor, ACT_DELETE, type(self)))
        if IQEditableEvaluation.providedBy(self.context):
            package = find_interface(self.context, IEditableContentPackage, strict=False)
            if package is not None:
                acl = get_cache_acl(package, acl_cache)
                result.extend(acl)
            # Editable evaluations can only be viewed if the user has course
            # permissions.
            result.append(ACE_DENY_ALL)
        # Package backed evaluations end up getting permission based on the package ACL.
        return result
