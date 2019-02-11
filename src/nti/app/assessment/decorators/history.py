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

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_RESET_EVALUATION

from nti.app.assessment.common.history import get_user_submission_count
from nti.app.assessment.common.history import get_most_recent_history_item

from nti.app.assessment.common.policy import get_policy_max_submissions
from nti.app.assessment.common.policy import is_policy_max_submissions_unlimited

from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemContainer

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.courses.utils import get_parent_course
from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.interfaces import IUser

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IExternalMappingDecorator)
class _AssignmentsAvailableAssignmentHistoryDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    For a user's assignment history, expose available assignments.
    """

    def _user_predicate(self, user, course):
        return get_course_assessment_predicate_for_user(user, course)

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        user = context.owner
        courses = set()
        # Course request context specific
        context_course = _get_course_from_evaluation(context,
                                                     user=self.remoteUser,
                                                     request=self.request)
        if context_course is not None:
            courses.add(context_course)
            parent_course = get_parent_course(context_course)
            courses.add(parent_course)
            result = set()
            # Get all parnet/section assignments available to student.
            for course in courses:
                assignment_catalog = ICourseAssignmentCatalog(course)
                user_predicate = self._user_predicate(user, course)
                result.update(asg.ntiid
                              for asg in assignment_catalog.iter_assignments()
                              if user_predicate(asg))
            result_map['AvailableAssignmentNTIIDs'] = sorted(result)


@interface.implementer(IExternalMappingDecorator)
class _CourseAssignmentHistoryDecorator(AbstractAssessmentDecoratorPredicate):
    """
    For things that have an assignment history, add this as a link.
    """

    # Note: This overlaps with the registrations in assessment_views
    # Note: We do not specify what we adapt, there are too many
    # things with no common ancestor.

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        links = result_map.setdefault(LINKS, [])
        # If the context provides a user, that's the one we want,
        # otherwise we want the current user
        user = IUser(context, self.remoteUser)
        links.append(Link(context,
                          rel='AssignmentHistory',
                          elements=('AssignmentHistories', user.username)))


class _LastViewedAssignmentHistoryDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    For assignment histories, when the requester is the owner,
    we add a link to point to the 'lastViewed' update spot.
    """

    def _predicate(self, context, unused_result):
        return (    self._is_authenticated
                and context.owner is not None
                and context.owner == self.remoteUser)

    def _do_decorate_external(self, context, result):
        links = result.setdefault(LINKS, [])
        links.append(Link(context,
                          rel='lastViewed',
                          elements=('@@lastViewed',),
                          method='PUT'))


@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
    """
    A rel to get the history item for this assignment and user. Now that we may
    multiple submissions for a user/course/assignment, we return a rel pointing
    to the most recent submission for bwc.

    Also decorate a `Histories` rel to return all submissions.
    """

    @Lazy
    def _catalog(self):
        result = component.getUtility(ICourseCatalog)
        return result

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        user = self.remoteUser
        links = result_map.setdefault(LINKS, [])
        course = _get_course_from_evaluation(context,
                                             user,
                                             self._catalog,
                                             request=self.request)
        history_item = get_most_recent_history_item(user, course, context.ntiid)
        submission_count = get_user_submission_count(user,
                                                     course,
                                                     context)

        # Check submission count
        result_map['submission_count'] = submission_count
        max_submissions = get_policy_max_submissions(context, course)
        if     not submission_count \
            or max_submissions > submission_count \
            or is_policy_max_submissions_unlimited(context, course):
            # The user can submit; note we do not check admin status here
            link = Link(course,
                        rel='Submit',
                        method='POST',
                        elements=('Assessments', context.ntiid))
            links.append(link)
        if history_item is not None:
            links.append(Link(history_item, rel='History'))
            links.append(Link(course,
                              rel='Histories',
                              elements=('AssignmentHistories',
                                        user.username,
                                        context.ntiid)))


@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemDecorator(_AbstractTraversableLinkDecorator):

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        remoteUser = self.remoteUser
        course = find_interface(context, ICourseInstance, strict=False)
        if course is None:
            return
        # Get the metadata attempt for this history item
        result_map['MetadataAttemptItem'] = IUsersCourseAssignmentAttemptMetadataItem(context, None)
        result_map['AssignmentId'] = context.assignmentId
        result_map['submission_count'] = get_user_submission_count(remoteUser,
                                                                   course,
                                                                   context.assignmentId)
        # Decorate a rel to the container itself
        _links = result_map.setdefault(LINKS, [])
        link = Link(context.__parent__,
                    rel='HistoryItemContainer')
        interface.alsoProvides(link, ILocation)
        link.__name__ = ''
        link.__parent__ = context
        _links.append(link)


@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemContainerDecorator(_AbstractTraversableLinkDecorator):

    def _predicate(self, context, unused_result):
        return len(context)

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        course = find_interface(context, ICourseInstance, strict=False)
        if course is None:
            return
        if      ICourseInstance.providedBy(course) \
            and is_course_instructor(course, self.remoteUser):
            _links = result_map.setdefault(LINKS, [])
            link = Link(context,
                        rel=VIEW_RESET_EVALUATION,
                        elements=('@@' + VIEW_RESET_EVALUATION,),
                        method='POST')
            interface.alsoProvides(link, ILocation)
            link.__name__ = ''
            link.__parent__ = context
            _links.append(link)


@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemSummaryDecorator(_AssignmentHistoryItemContainerDecorator):

    def _predicate(self, context, unused_result):
        return True

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        item_container = find_interface(context,
                                        IUsersCourseAssignmentHistoryItemContainer,
                                        strict=False)
        if len(item_container):
            super(_AssignmentHistoryItemSummaryDecorator, self)._do_decorate_external(item_container, result_map)
        # Decorate a rel to the container itself
        _links = result_map.setdefault(LINKS, [])
        link = Link(item_container,
                    rel='HistoryItemContainer')
        interface.alsoProvides(link, ILocation)
        link.__name__ = ''
        link.__parent__ = context
        _links.append(link)
