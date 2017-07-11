#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
from io import BytesIO

from datetime import datetime

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.security.management import checkPermission

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import inquiry_submissions
from nti.app.assessment.common import can_disclose_inquiry
from nti.app.assessment.common import aggregate_page_inquiry
from nti.app.assessment.common import get_course_from_inquiry
from nti.app.assessment.common import aggregate_course_inquiry
from nti.app.assessment.common import check_submission_version
from nti.app.assessment.common import get_available_for_submission_ending
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import ICourseAggregatedInquiries

from nti.app.assessment.survey import UsersCourseInquiryItemResponse

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views import MessageFactory as _

from nti.app.assessment.views import get_ds2

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware_reports.interfaces import ACT_VIEW_REPORTS

from nti.app.renderers.interfaces import INoHrefInResponse

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQSubmittable
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQAggregatedSurvey
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQInquirySubmission
from nti.assessment.interfaces import IQNonGradableConnectingPart
from nti.assessment.interfaces import IQNonGradableFreeResponsePart
from nti.assessment.interfaces import IQNonGradableMultipleChoicePart
from nti.assessment.interfaces import IQNonGradableModeledContentPart
from nti.assessment.interfaces import IQNonGradableMultipleChoiceMultipleAnswerPart

from nti.common.string import is_true

from nti.contentfragments.interfaces import IPlainTextContentFragment

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver import authorization as nauth
from nti.dataserver.users.interfaces import IFriendlyNamed

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.oids import to_external_ntiid_oid

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
CREATOR = StandardExternalFields.CREATOR
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


def allow_to_disclose_inquiry(context, course, user):
    if not is_course_instructor(course, user):
        if not can_disclose_inquiry(context, course):
            return False
    return True


class InquiryViewMixin(object):

    @Lazy
    def course(self):
        creator = self.remoteUser
        if not creator:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Must be Authenticated.")
                             },
                             None)
        course = get_course_from_request(self.request)
        if course is None:
            course = get_course_from_inquiry(self.context, creator, exc=False)
        if course is None:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Must be enrolled in a course.")
                             },
                             None)
        return course


@view_config(route_name="objects.generic.traversal",
             context=IQInquiry,
             renderer='rest',
             request_method='POST',
             permission=nauth.ACT_READ)
class InquirySubmissionPostView(AbstractAuthenticatedView,
                                ModeledContentUploadRequestUtilsMixin,
                                InquiryViewMixin):

    _EXTRA_INPUT_ERRORS = ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + \
        (AttributeError,)

    content_predicate = IQInquirySubmission.providedBy

    def _check_poll_submission(self, submission):
        poll = component.getUtility(IQPoll, name=submission.inquiryId)
        if len(poll.parts) != len(submission.parts):
            ex = ConstraintNotSatisfied(_(u"Incorrect submission parts."))
            ex.field = IQPollSubmission['parts']
            raise ex

    def _check_submission_before(self, course):
        beginning = get_available_for_submission_beginning(
            self.context, course)
        if beginning is not None and datetime.utcnow() < beginning:
            ex = ConstraintNotSatisfied(_(u"Submitting too early."))
            ex.field = IQSubmittable['available_for_submission_beginning']
            ex.value = beginning
            raise ex

    def _check_submission_ending(self, course):
        ending = get_available_for_submission_ending(self.context, course)
        if ending is not None and datetime.utcnow() > ending:
            ex = ConstraintNotSatisfied(_(u"Submitting too late."))
            ex.field = IQSubmittable['available_for_submission_ending']
            raise ex

    def _check_inquiry_close(self):
        if self.context.closed:
            ex = ConstraintNotSatisfied(_(u"Inquiry has been closed."))
            ex.field = IQInquiry['closed']
            raise ex

    def _check_version(self, submission):
        check_submission_version(submission, self.context)

    def _do_call(self):
        course = self.course
        creator = self.remoteUser
        self._check_inquiry_close()
        self._check_submission_before(course)
        self._check_submission_ending(course)

        submission = self.readCreateUpdateContentObject(creator)
        self._check_version(submission)

        # Check that the submission has something for all polls
        if IQSurveySubmission.providedBy(submission):
            survey = component.getUtility(IQSurvey, name=submission.inquiryId)
            survey_poll_ids = [poll.ntiid for poll in survey.questions]
            submission_poll_ids = [
                poll.pollId for poll in submission.questions
            ]
            if sorted(survey_poll_ids) != sorted(submission_poll_ids):
                msg = _(u"Incorrect submission questions.")
                ex = ConstraintNotSatisfied(msg)
                ex.field = IQSurveySubmission['questions']
                raise ex
            for question_sub in submission.questions:
                self._check_poll_submission(question_sub)
        elif IQPollSubmission.providedBy(submission):
            self._check_poll_submission(submission)

        creator = submission.creator
        course_inquiry = component.getMultiAdapter((course, creator),
                                                   IUsersCourseInquiry)
        submission.containerId = submission.inquiryId

        if submission.inquiryId in course_inquiry:
            ex = NotUnique(_(u"Inquiry already submitted."))
            ex.field = IQInquirySubmission['inquiryId']
            ex.value = submission.inquiryId
            raise ex

        version = self.context.version
        if version is not None:  # record version
            submission.version = version

        # Now record the submission.
        self.request.response.status_int = 201
        recorded = course_inquiry.recordSubmission(submission)
        result = UsersCourseInquiryItemResponse(Submission=recorded)
        if allow_to_disclose_inquiry(self.context, course, self.remoteUser):
            result.Aggregated = aggregate_course_inquiry(self.context,
                                                         course,
                                                         recorded)

        result = to_external_object(result)
        result['href'] = "/%s/Objects/%s" % (get_ds2(self.request),
                                             to_external_ntiid_oid(recorded))
        interface.alsoProvides(result, INoHrefInResponse)

        return result


@view_config(route_name="objects.generic.traversal",
             context=IQInquiry,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="Submission")
class InquirySubmissionGetView(AbstractAuthenticatedView, InquiryViewMixin):

    def __call__(self):
        course = self.course
        creator = self.remoteUser
        course_inquiry = component.getMultiAdapter((course, creator),
                                                   IUsersCourseInquiry)
        try:
            return course_inquiry[self.context.ntiid]
        except KeyError:
            return hexc.HTTPNotFound()


@view_config(route_name="objects.generic.traversal",
             context=IQInquiry,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="Submissions")
class InquirySubmissionsView(AbstractAuthenticatedView, InquiryViewMixin):

    def __call__(self):
        course = self.course
        if not (is_course_instructor(course, self.remoteUser)
                or has_permission(nauth.ACT_NTI_ADMIN, course, self.request)):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot get inquiry submissions.")
                             },
                             None)
        result = LocatedExternalDict()
        queried = inquiry_submissions(self.context, course)

        def _key(item):
            lastModified = item.lastModified
            creator = getattr(item.creator, 'username', item.creator)
            return (lastModified, creator or u'')

        def _ext_obj(item):
            result = to_external_object(item, decorate=False)
            result.pop(CREATOR, None)
            result.pop('questions', None)
            return result

        items = result[ITEMS] = [
            _ext_obj(x.Submission) for x in sorted(queried, key=_key)
        ]
        result['Inquiry'] = to_external_object(self.context, decorate=False)
        result[TOTAL] = result[ITEM_COUNT] = len(items)
        return result


@view_config(route_name="objects.generic.traversal",
             context=IQInquiry,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="SubmissionMetadata")
class InquirySubmissionMetadataCSVView(AbstractAuthenticatedView, InquiryViewMixin):

    def __call__(self):
        course = self.course
        if not (is_course_instructor(course, self.remoteUser)
                or has_permission(nauth.ACT_NTI_ADMIN, course, self.request)):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot get inquiry submissions.")
                             },
                             None)
        queried = inquiry_submissions(self.context, course)

        response = self.request.response
        response.content_encoding = 'identity'
        response.content_type = 'text/csv; charset=UTF-8'
        metadata = _get_title_for_metadata_download(self.context.title)
        response.content_disposition = 'attachment; filename="%s"' % metadata

        stream = BytesIO()
        fieldnames = ['username', 'realname', 'email', 'submission_time']
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()

        items = [x for x in sorted(queried, key=lambda x: x.createdTime)]

        for item in items:
            user = IFriendlyNamed(item.creator)
            username = getattr(user, 'username', '')
            realname = getattr(user, 'realname', '')
            email = getattr(user, 'email', '')
            submission_time_str = _date_str_from_timestamp(item.createdTime)
            data = {'username': username,
                    'realname': realname,
                    'email': email,
                    'submission_time': submission_time_str}
            writer.writerow(data)

        stream.flush()
        stream.seek(0)
        response.body_file = stream
        return response


def _get_title_for_metadata_download(inquiry_name):
    ascii_str = inquiry_name.encode('ascii', 'ignore')
    return u'%s_SubmissionMetadata.csv' % ascii_str.replace(' ', '')


def _date_str_from_timestamp(timestamp):
    submission_time = datetime.utcfromtimestamp(timestamp)
    return submission_time.strftime('%m-%d-%Y')


@view_config(route_name="objects.generic.traversal",
             renderer='rest',
             context=IUsersCourseInquiries,
             permission=nauth.ACT_READ,
             request_method='GET')
class InquiriesGetView(AbstractAuthenticatedView):
    """
    Students can view their survey/polls submissions as ``path/to/course/Inquiries``
    """

    def __call__(self):
        result = self.request.context
        return result


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseInquiryItem,
             renderer='rest',
             permission=nauth.ACT_DELETE,
             request_method='DELETE')
class InquiryItemDeleteView(UGDDeleteView):

    def _do_delete_object(self, theObject):
        del theObject.__parent__[theObject.__name__]
        return theObject


@view_config(name='close')
@view_config(name='Close')
@view_defaults(route_name="objects.generic.traversal",
               context=IQInquiry,
               renderer='rest',
               request_method='POST',
               permission=nauth.ACT_READ)
class InquiryCloseView(AbstractAuthenticatedView, InquiryViewMixin):

    def __call__(self):
        course = self.course
        if not is_course_instructor(course, self.remoteUser):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot close inquiry.")
                             },
                             None)
        self.context.closed = True
        result = aggregate_course_inquiry(self.context, course)
        container = ICourseAggregatedInquiries(course)
        container[self.context.ntiid] = result
        return result


@view_config(name='open')
@view_config(name='Open')
@view_defaults(route_name="objects.generic.traversal",
               context=IQInquiry,
               renderer='rest',
               request_method='POST',
               permission=nauth.ACT_READ)
class InquiryOpenView(AbstractAuthenticatedView, InquiryViewMixin):

    def __call__(self):
        course = self.course
        if not is_course_instructor(course, self.remoteUser):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot open inquiry.")
                             },
                             None)
        self.context.closed = False
        try:
            container = ICourseAggregatedInquiries(course)
            del container[self.context.ntiid]
        except KeyError:
            pass
        return hexc.HTTPNoContent()


@view_config(route_name="objects.generic.traversal",
             context=IQInquiry,
             renderer='rest',
             request_method='GET',
             permission=nauth.ACT_READ,
             name="Aggregated")
class InquiryAggregatedGetView(AbstractAuthenticatedView, InquiryViewMixin):

    def __call__(self):
        course = self.course
        if not allow_to_disclose_inquiry(self.context, course, self.remoteUser):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot disclose inquiry results.")
                             },
                             None)
        if self.context.closed:
            container = ICourseAggregatedInquiries(course)
            result = container[self.context.ntiid]
        else:
            result = aggregate_course_inquiry(self.context, course)
        if result is None:
            return hexc.HTTPNoContent()

        if      IQAggregatedSurvey.providedBy( result ) \
                and IQPoll.providedBy(self.context):
            # Asking for question level aggregation for
            # survey submissions.
            for poll_result in result.questions or ():
                if poll_result.inquiryId == self.context.ntiid:
                    result = poll_result
                    break
        return result


@view_config(route_name="objects.generic.traversal",
             context=IQInquirySubmission,
             renderer='rest',
             permission=nauth.ACT_READ,
             request_method='POST')
class InquirySubmisionPostView(UGDPostView):

    def __call__(self):
        result = super(InquirySubmisionPostView, self).__call__()
        inquiry = component.getUtility(IQInquiry, name=self.context.inquiryId)
        if can_disclose_inquiry(inquiry):
            mimeType = self.context.mimeType
            containerId = self.context.containerId
            result = aggregate_page_inquiry(containerId,
                                            mimeType,
                                            self.context)
        return result


@view_config(route_name="objects.generic.traversal",
             context=IQInquirySubmission,
             renderer='rest',
             permission=nauth.ACT_READ,
             request_method='PUT')
class InquirySubmisionPutView(UGDPutView):

    def __call__(self):
        raise_json_error(self.request,
                         hexc.HTTPForbidden,
                         {
                             'message': _(u"Cannot put an inquiry submission.")
                         },
                         None)


def plain_text(s):
    result = IPlainTextContentFragment(s) if s else u''
    return result.strip()


def display_list(data):
    result = []
    for item in data[:-1]:
        result.append('%s, ' % item)
    result.append('%s' % data[-1])
    return u''.join(result)


@view_config(route_name="objects.generic.traversal",
             context=IQSurvey,
             name='InquiryReport.csv',
             renderer='rest',
             permission=nauth.ACT_READ,
             request_method='GET')
class SurveyReportCSV(AbstractAuthenticatedView, InquiryViewMixin):

    @property
    def questions(self):
        return self.context.questions

    def __call__(self):
        # only users with reports permissions should be able to view this.
        if not checkPermission(ACT_VIEW_REPORTS.id, self.course):
            raise hexc.HTTPForbidden()

        params = self.request.params
        include_usernames = is_true(params.get('include_usernames'))

        stream = BytesIO()
        csv_writer = csv.writer(stream)

        # only include the usernames if specified with a param
        if include_usernames:
            header_row = ['user']
        else:
            header_row = []
        for question in self.questions:
            if len(question.parts) > 1:
                # If the question has more than one part, we need to
                # create a column for each part of the question.
                for part in question.parts:
                    header_row.append(plain_text(question.content) + ": " +
                                      plain_text(part.content))
            else:
                header_row.append(plain_text(question.content))

        csv_writer.writerow(header_row)
        user_rows = []

        submissions = inquiry_submissions(self.context, self.course)
        for item in submissions:
            if not IUsersCourseInquiryItem.providedBy(item):  # always check
                continue
            subs_questions = item.Submission.questions
            if include_usernames:
                row = [item.creator.username]
            else:
                row = []
            for question in sorted(subs_questions, key=lambda x: x.inquiryId, reverse=True):
                poll = component.queryUtility(IQPoll, name=question.inquiryId)
                for part_idx, part in enumerate(zip(question.parts, poll.parts)):
                    responses = []
                    question_part, poll_part = part
                    if question_part is None:
                        # If the question part is None, the user did not respond
                        # to this question, and we should put in a placeholder for
                        # this question.
                        result = u''
                        continue
                    # Each type of question is handled slightly differently.
                    if IQNonGradableConnectingPart.providedBy(poll_part):
                        # need this to be sorted by value. Since the response
                        # values come from a dictionary, they may not be in the right order
                        # otherwise. We need to make sure to assign the correct label
                        # for each response.
                        response_values = sorted(
                            question_part.items(), key=lambda x: x[1]
                        )
                        part_values = poll.parts[part_idx].values
                        part_labels = [plain_text(x) for x in part_values]
                        # We look up by key from the response values in order
                        # to get the label for this choice.
                        result = [
                            part_labels[int(k[0])] for k in response_values
                        ]
                        result = display_list(result)
                    elif IQNonGradableMultipleChoiceMultipleAnswerPart.providedBy(poll_part):
                        response_values = question_part
                        part_values = poll.parts[part_idx].choices
                        result = [
                            plain_text(part_values[int(k)]) for k in response_values
                        ]
                        result = display_list(result)
                    elif IQNonGradableMultipleChoicePart.providedBy(poll_part):
                        part_values = poll.parts[part_idx].choices
                        result = plain_text(part_values[int(question_part)])
                    elif IQNonGradableModeledContentPart.providedBy(poll_part):
                        result = question_part.value[0]
                    elif IQNonGradableFreeResponsePart.providedBy(poll_part):
                        result = plain_text(question_part)
                    # add to result
                    responses.append(result)
                    row.extend(responses)
            user_rows.append(row)

        # If we have usernames, we should sort by that column.
        if include_usernames:
            user_rows = sorted(user_rows, key=lambda x: x[0])

        for row in user_rows:
            csv_writer.writerow(row)
        stream.flush()
        stream.seek(0)
        self.request.response.content_type = 'application/octet-stream'
        self.request.response.body_file = stream
        return self.request.response
