#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from datetime import datetime

from zope import component
from zope import interface

from zope.intid.interfaces import IIntIds

from nti.app.assessment.common import inquiry_submissions
from nti.app.assessment.common import can_disclose_inquiry
from nti.app.assessment.common import get_policy_for_assessment
from nti.app.assessment.common import get_available_for_submission_ending
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.decorators import _root_url
from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import _AbstractTraversableLinkDecorator
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ILinkExternalHrefOnly

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.property.property import Lazy

from nti.traversal.traversal import find_interface

LINKS = StandardExternalFields.LINKS
CREATOR = StandardExternalFields.CREATOR


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
        course = find_interface(context, ICourseInstance, strict=False)
        if course is None:
            course = _get_course_from_evaluation(context,
                                                 user,
                                                 self._catalog,
                                                 request=self.request)
        return course

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
