#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from nti.app.assessment.common.history import get_assessment_metadata_item

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQTimedAssignment

from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ILinkExternalHrefOnly

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS


class _AssignmentSavepointDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, unused_result):
        """
        Do not decorate non-started timed assignments.
        """
        user = self.remoteUser
        course = _get_course_from_evaluation(context,
                                             user=self.remoteUser,
                                             request=self.request)
        # Instructors/editors do not get savepoint links.
        result = not(   is_course_instructor_or_editor(course, user)
                     or has_permission(ACT_CONTENT_EDIT, context, self.request))

        if      result \
            and IQTimedAssignment.providedBy(context) \
            and course is not None:
            item = get_assessment_metadata_item(course, user, context.ntiid)
            result = bool(item is not None and item.StartTime)
        return result

    def _do_decorate_external(self, assignment, result):
        user = self.remoteUser
        course = _get_course_from_evaluation(assignment, user, request=self.request)
        if course is not None and user != None:
            links = result.setdefault(LINKS, [])
            links.append(Link(course,
                              rel='Savepoint',
                              elements=('AssignmentSavepoints', user.username,
                                        assignment.ntiid, 'Savepoint')))


@interface.implementer(IExternalMappingDecorator)
class _AssignmentSavepointsDecorator(AbstractAssessmentDecoratorPredicate):

    def _do_decorate_external(self, context, result_map):
        links = result_map.setdefault(LINKS, [])
        user = IUser(context, self.remoteUser)
        links.append(Link(context,
                          rel='AssignmentSavepoints',
                          elements=('AssignmentSavepoints', user.username)))


@interface.implementer(IExternalMappingDecorator)
class _AssignmentSavepointItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, result):
        creator = context.creator
        return (    AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
                and creator is not None
                and creator == self.remoteUser)

    def _do_decorate_external(self, context, result_map):
        try:
            link = Link(context)
            interface.alsoProvides(link, ILinkExternalHrefOnly)
            result_map['href'] = link
        except (KeyError, ValueError, AssertionError):
            pass  # Nope
