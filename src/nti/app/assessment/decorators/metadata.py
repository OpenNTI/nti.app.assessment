#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ILinkExternalHrefOnly

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.ntiids.ntiids import find_object_with_ntiid

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


class _AssignmentMetadataDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    For an assigment, return rels to fetch the metadata container for this
    user/course/assignment as well as the commence rels.
    """

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, assignment, result):
        user = self.remoteUser
        course = _get_course_from_evaluation(assignment,
                                             user,
                                             request=self.request)
        if course is None:
            return

        # pylint: disable=no-member
        elements = ('AssignmentAttemptMetadata', user.username, assignment.ntiid)

        links = result.setdefault(LINKS, [])
        links.append(Link(course,
                          rel='Metadata',
                          elements=elements + ('Metadata',)))

        # All assignments can commence
        # Always have a Start rel
        links.append(Link(course,
                          method='POST',
                          rel='Commence',
                          elements=elements + ('@@Commence',)))


class _AssignmentAttemptMetadataItemDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    For a :class:`IUsersCourseAssignmentAttemptMetadataItem`, give links to
    fetch the history item as well as the assignment via this context.

    TimedAssignment meta will also have rels to fetch start time and time
    remaining.
    """

    def _predicate(self, context, result):
        creator = context.creator
        return (     AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
                 and creator is not None
                 and creator == self.remoteUser)

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, metadata_item, result):
        try:
            link = Link(metadata_item)
            interface.alsoProvides(link, ILinkExternalHrefOnly)
            result['href'] = link
        except (KeyError, ValueError, AssertionError):
            pass  # Nope

        user = self.remoteUser
        container = metadata_item.__parent__
        evaluation = find_object_with_ntiid(container.__name__)
        course = _get_course_from_evaluation(evaluation,
                                             user,
                                             request=self.request)
        if course is None:
            return

        # pylint: disable=no-member
        elements = ('AssignmentAttemptMetadata',
                    user.username,
                    evaluation.ntiid,
                    metadata_item.__name__)

        links = result.setdefault(LINKS, [])
        for rel in ('HistoryItem', 'Assignment'):
            links.append(Link(course,
                              method='GET',
                              rel=rel,
                              elements=elements + ('@@' + rel,)))

        if IQTimedAssignment.providedBy(evaluation):
            for rel in ('StartTime', 'TimeRemaining'):
                links.append(Link(course,
                                  method='GET',
                                  rel=rel,
                                  elements=elements + ('@@' + rel,)))


@interface.implementer(IExternalMappingDecorator)
class _AssignmentMetadataContainerDecorator(AbstractAssessmentDecoratorPredicate):
    """
    Return the metadata container (all assignments) for the user enrollment record.
    """

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        links = result_map.setdefault(LINKS, [])
        user = IUser(context, self.remoteUser)
        links.append(Link(context,
                          rel='AssignmentAttemptMetadata',
                          elements=('AssignmentAttemptMetadata', user.username)))
