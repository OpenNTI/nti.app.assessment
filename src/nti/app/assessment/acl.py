#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_editors
from nti.contenttypes.courses.utils import content_unit_to_courses

from nti.dataserver.authorization import ACT_DELETE
from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.interfaces import IACLProvider

from nti.property.property import Lazy

from nti.traversal.traversal import find_interface


def get_evaluation_courses(context):
    course = find_interface(context, ICourseInstance, strict=False)
    if course is not None:  # editable evals
        result = (course,)
    else:  # legacy
        package = find_interface(context, IContentPackage, strict=False)
        result = content_unit_to_courses(
            package) if package is not None else ()
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
                ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
        result = acl_from_aces(aces)
        # Extend with any course acls.
        courses = get_evaluation_courses(self.context)
        for course in courses or ():
            result.extend(IACLProvider(course).__acl__)
            if IQEditableEvaluation.providedBy(self.context):
                for editor in get_course_editors(course):
                    result.append(ace_allowing(editor, ACT_DELETE, type(self)))
        return result
