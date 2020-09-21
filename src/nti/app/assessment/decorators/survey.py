#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=arguments-differ

from datetime import datetime
from pyramid.threadlocal import get_current_request

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.intid.interfaces import IIntIds

from zope.location import ILocation

from nti.app.assessment import VIEW_DELETE
from nti.app.assessment import VIEW_INSERT_PART
from nti.app.assessment import VIEW_INSERT_PART_OPTION
from nti.app.assessment import VIEW_INSERT_POLL
from nti.app.assessment import VIEW_MOVE_PART
from nti.app.assessment import VIEW_MOVE_PART_OPTION
from nti.app.assessment import VIEW_MOVE_POLL
from nti.app.assessment import VIEW_REMOVE_PART
from nti.app.assessment import VIEW_REMOVE_PART_OPTION
from nti.app.assessment import VIEW_REMOVE_POLL

from nti.app.assessment.common.inquiries import can_disclose_inquiry

from nti.app.assessment.common.policy import get_policy_for_assessment

from nti.app.assessment.common.submissions import inquiry_submissions

from nti.app.assessment.common.utils import get_available_for_submission_ending

from nti.app.assessment.common.utils import get_available_for_submission_beginning

from nti.app.assessment.decorators import _root_url
from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiryItem

from nti.app.assessment.utils import get_course_from_request

from nti.app.authentication import get_remote_user

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment import IQPoll

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_editor
from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.authorization import ACT_CONTENT_EDIT
from nti.dataserver.authorization import ACT_NTI_ADMIN

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ILinkExternalHrefOnly

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS
CREATOR = StandardExternalFields.CREATOR

logger = __import__('logging').getLogger(__name__)


class _InquiryContentRootURLAdder(AbstractAuthenticatedRequestAwareDecorator):

    def _do_decorate_external(self, context, result):
        ntiid = getattr(context, 'ContentUnitNTIID', None)
        if not ntiid:
            content_unit = find_interface(context, IContentUnit, strict=False)
            if content_unit is not None:
                ntiid = content_unit.ntiid
            else:
                assignment = find_interface(context, IQSurvey, strict=False)
                ntiid = getattr(assignment, 'ContentUnitNTIID', None)

        bucket_root = _root_url(ntiid) if ntiid else None
        if bucket_root:
            result['ContentRoot'] = bucket_root


@interface.implementer(IExternalMappingDecorator)
class _InquiriesDecorator(AbstractAssessmentDecoratorPredicate):

    def _do_decorate_external(self, context, result_map):
        links = result_map.setdefault(LINKS, [])
        user = IUser(context, self.remoteUser)
        links.append(Link(context,
                          rel='InquiryHistory',
                          elements=('Inquiries', user.username)))


@interface.implementer(IExternalMappingDecorator)
class _InquiryItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

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


@component.adapter(IQPollSubmission)
@component.adapter(IQSurveySubmission)
@interface.implementer(IExternalMappingDecorator)
class _SubmissionDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _do_decorate_external(self, context, result_map):
        item = find_interface(context, IUsersCourseInquiryItem, strict=False)
        if item is not None and CREATOR not in result_map:
            creator = getattr(item.creator, 'username', item.creator)
            result_map[CREATOR] = creator


@interface.implementer(IExternalMappingDecorator)
class _InquiryDecorator(_AbstractTraversableLinkDecorator):

    @Lazy
    def _catalog(self):
        return component.getUtility(ICourseCatalog)

    @Lazy
    def _intids(self):
        return component.getUtility(IIntIds)

    def _submissions(self, course, context):
        return len(inquiry_submissions(context, course))

    def _predicate(self, context, result):
        context = IQInquiry(context, None)
        if context is not None:
            return super(_InquiryDecorator, self)._predicate(context, result)
        return False

    def _get_course(self, context, user):
        # We may have survey in multiple courses (if decorating survey ref), use our
        # ref lineage to distinguish between multiple courses. Ideally, we'll want
        # to make sure we have a course context wherever this ref is being accessed
        # (lesson overview) to handle subinstances correctly.
        course = get_course_from_request()
        if course is None:
            course = find_interface(context, ICourseInstance, strict=False)
            if course is None:
                course = _get_course_from_evaluation(context,
                                                     user,
                                                     self._catalog,
                                                     request=self.request)
        return course

    def _get_poll_rels(self):
        """
        Gather any links needed for a non-in-progress editable polls.
        """
        return (VIEW_MOVE_PART,
                VIEW_INSERT_PART,
                VIEW_REMOVE_PART,
                VIEW_MOVE_PART_OPTION,
                VIEW_INSERT_PART_OPTION,
                VIEW_REMOVE_PART_OPTION)

    def _get_survey_rels(self):
        """
        Gather any links needed for a non-in-progress editable surveys.
        """
        return (VIEW_MOVE_POLL, VIEW_INSERT_POLL, VIEW_REMOVE_POLL, VIEW_DELETE)

    def _do_decorate_external(self, context, result_map):
        source = context
        user = self.remoteUser
        context = IQInquiry(source, None)
        if context is None:
            return

        isClosed = bool(context.closed)
        result_map['isClosed'] = isClosed

        links = result_map.setdefault(LINKS, [])
        # See note above on why we get course for inquiry ref.
        ref_course = self._get_course(source, user)
        course = self._get_course(context, user)
        submission_count = 0

        # overrides
        if course is not None:
            submission_count = self._submissions(ref_course, context)
            available = []
            now = datetime.utcnow()
            # pylint: disable=too-many-function-args
            dates = IQAssessmentDateContext(course).of(context)
            for k, func in (
                    ('available_for_submission_beginning', get_available_for_submission_beginning),
                    ('available_for_submission_ending', get_available_for_submission_ending)):
                dates_date = func(dates, k)
                asg_date = getattr(context, k)
                if dates_date != asg_date:
                    result_map[k] = to_external_object(dates_date)
                    available.append(dates_date)
                else:
                    available.append(asg_date)

            if available[0] is not None and now < available[0]:
                isClosed = result_map['isClosed'] = True
            elif available[1] is not None and now > available[1]:
                isClosed = result_map['isClosed'] = True

            policy = get_policy_for_assessment(context, course)
            if policy and 'disclosure' in policy:
                result_map['disclosure'] = policy['disclosure']

            result_map['submissions'] = submission_count

        # pylint: disable=no-member
        elements = ('Inquiries', user.username, context.ntiid)

        course_inquiry = component.queryMultiAdapter((course, user),
                                                     IUsersCourseInquiry)
        # history
        if course is not None and course_inquiry and context.ntiid in course_inquiry:
            links.append(Link(course,
                              rel='History',
                              elements=elements + ('Submission',)))

        # aggregated
        if      course is not None \
            and submission_count \
            and (   is_course_instructor(course, user)
                 or can_disclose_inquiry(context, course)):
            links.append(Link(course,
                              rel='Aggregated',
                              elements=elements + ('@@Aggregated',)))
            links.append(Link(course,
                              rel='Submissions',
                              elements=elements + ('@@Submissions',)))

        # close/open
        if course is not None and is_course_instructor(course, user):
            if not context.closed:
                links.append(Link(course,
                                  rel='close',
                                  method='POST',
                                  elements=elements + ('@@close',)))
            else:
                links.append(Link(course,
                                  rel='open',
                                  method='POST',
                                  elements=elements + ('@@open',)))

        # editors
        if not context.is_published() and _is_editable(context, self.request):
            rels = []
            # Do not provide structural links if evaluation has submissions.
            if IQSurvey.providedBy(context):
                rels.extend(self._get_survey_rels())
            elif IQPoll.providedBy(context):
                rels.extend(self._get_poll_rels())

            # chose link context according to the presence of a course
            start_elements = ()
            link_context = context if course is None else course
            if course is not None:
                start_elements = ('Assessments', context.ntiid)

            # loop through rels and create links
            for rel in rels:
                elements = None if not start_elements else start_elements
                link = Link(link_context, rel=rel, elements=elements)
                interface.alsoProvides(link, ILocation)
                link.__name__ = ''
                link.__parent__ = link_context
                links.append(link)


class _InquirySubmissionMetadataDecorator(_InquiryDecorator):

    def _do_decorate_external(self, context, result_map):
        user = self.remoteUser
        links = result_map.setdefault(LINKS, [])
        course = self._get_course(context, user)
        if course is not None \
            and (   is_course_instructor(course, user)
                 or has_permission(ACT_NTI_ADMIN, course, self.request)):
            links.append(Link(course,
                              method='GET',
                              rel='submission_metadata',
                              elements=('CourseInquiries', 
                                         context.ntiid, 
                                        '@@SubmissionMetadata',)))

def _is_editable(context, request=None):
    request = request or get_current_request()
    user = get_remote_user(request)
    return (IQEditableEvaluation.providedBy(context)
            and (is_course_editor(context, user)
                 or has_permission(ACT_CONTENT_EDIT, context, request)
                 or is_course_instructor(context, user)))

class _PollPreflightDecorator(_InquiryDecorator):

    def _predicate(self, context, result):
        result = super(_PollPreflightDecorator, self)._predicate(context, result)
        return (result and _is_editable(context, self.request))

    def _do_decorate_external(self, context, result_map):
        links = result_map.setdefault(LINKS, [])
        links.append(Link(context,
                          method='PUT',
                          rel='preflight_update',
                          elements=('@@preflight',)))
