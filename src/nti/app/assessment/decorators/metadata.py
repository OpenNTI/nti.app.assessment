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

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadata

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ILinkExternalHrefOnly

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.ntiids.ntiids import find_object_with_ntiid
from nti.app.assessment.common.policy import get_policy_max_submissions

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
        # Remote user metadata for this course/assignment
        links.append(Link(course,
                          rel='Metadata',
                          elements=elements))

        user_container = component.queryMultiAdapter((course, user),
                                                     IUsersCourseAssignmentAttemptMetadata)
        meta_container = user_container.get(assignment.ntiid)
        meta_count = 0
        if meta_container:
            # Get the currently in-progress attempt, if it exists.
            meta_count = len(meta_container)
            for meta_item in meta_container.values():
                if not meta_item.SubmitTime:
                    result['MetadataAttemptItem'] = meta_item
                    break

        # All assignments can commence
        max_submissions = get_policy_max_submissions(assignment, course)
        if max_submissions and max_submissions > meta_count:
            # Always have a Start rel if they have not exceeded threshold
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

        rels = ('Assignment',)
        if metadata_item.HistoryItem is not None:
            rels = ('Assignment', "HistoryItem")

        if IQTimedAssignment.providedBy(evaluation):
            rels = rels + ('StartTime', 'TimeRemaining')

        links = result.setdefault(LINKS, [])
        for rel in rels:
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
