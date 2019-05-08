#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment submission/history

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import sys

from io import BytesIO
from numbers import Number
from datetime import datetime

from slugify import UniqueSlugify

from zipfile import ZIP_DEFLATED

from zipfile import ZipFile
from zipfile import ZipInfo

from zope import component

from zope.cachedescriptors.property import Lazy

from zope.container.traversal import ContainerTraversable

from zope.event import notify

from zope.location.interfaces import LocationError

from pyramid import httpexceptions as hexc

from pyramid.httpexceptions import HTTPCreated
from pyramid.httpexceptions import HTTPException

from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _
from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION
from nti.app.assessment import VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD

from nti.app.assessment._submission import get_source
from nti.app.assessment._submission import check_upload_files
from nti.app.assessment._submission import read_multipart_sources

from nti.app.assessment.common.evaluations import get_course_assignments
from nti.app.assessment.common.evaluations import is_assignment_available
from nti.app.assessment.common.evaluations import get_course_from_evaluation
from nti.app.assessment.common.evaluations import is_assignment_available_for_submission

from nti.app.assessment.common.history import get_most_recent_history_item

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.utils import replace_username
from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import assignment_download_precondition
from nti.app.assessment.utils import get_current_metadata_attempt_item
from nti.app.assessment.utils import course_assignments_download_precondition

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error
from nti.app.externalization.internalization import read_input_data

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.base.interfaces import IFile

from nti.contenttypes.completion.interfaces import UserProgressUpdatedEvent

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser

from nti.dataserver.users.interfaces import IUserProfile

from nti.dataserver.users.users import User


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             request_method='POST')
class AssignmentSubmissionPostView(AbstractAuthenticatedView,
                                   ModeledContentUploadRequestUtilsMixin):
    """
    Students can POST to the assignment to create their submission.
    """

    METADATA_ATTEMPT_VALIDATION = True

    # If the user submits a badly formed submission, we can get
    # this, especially if we try to autograde. (That particular case
    # is now handled, but still.)
    _EXTRA_INPUT_ERRORS = ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + \
                          (AttributeError,)

    # XXX: We would like to express access control via
    # an ACL or the zope security role map.
    # In the past, this more-or-less worked because there was
    # one piece of content defining one course containing assignments only
    # used by that course, and moreover, that course knew exactly about its
    # permissioning and was intimately tied to a global community that enrolled
    # users were put in. Thus, the .nti_acl file that defined access to the course content
    # also served for the assignment.
    # Now, however, we're in the situation where none of that holds: courses
    # are separate from content, and define their own permissioning. But assignments are
    # still defined from a piece of content and would inherit its permissions
    # if we let it.

    # Therefore, we simply do not specify a permission for this view, and instead
    # do an enrollment check.

    content_predicate = IQAssignmentSubmission.providedBy

    @Lazy
    def course(self):
        return get_course_from_request(self.request)

    def _validate_submission(self):
        creator = self.remoteUser
        if self.course is None:
            logger.warn('Submission for assessment without course context (user=%s)',
                        creator)
            msg = _(u"Submission for assessment without course context")
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': msg,
                             },
                             None)

        if not is_assignment_available(self.context, course=self.course, user=creator):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Assignment is not available."),
                             },
                             None)

        if not is_assignment_available_for_submission(self.context, course=self.course, user=creator):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Assignment is not available for submission."),
                                 'code': u'CannotSubmitAssignmentError'
                             },
                             None)
        if      self.METADATA_ATTEMPT_VALIDATION \
            and not get_current_metadata_attempt_item(creator, self.course, self.context.ntiid):
            # Code error
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u'Must have metadata attempt currently in progress'),
                                 'code': u'MissingMetadataAttemptInProgressError'
                             },
                             None)

    def _do_call(self):
        creator = self.remoteUser
        submission = None
        try:
            self._validate_submission()
            # We validate this is non-none and set on the request
            # The seed/randomization logic requires us to know our attempt
            # item in order to randomize correctly.
            attempt_item = get_current_metadata_attempt_item(creator, self.course, self.context.ntiid)
            self.request.meta_attempt_item_traversal_context = attempt_item
            if not self.request.POST:
                submission = self.readCreateUpdateContentObject(creator)
                check_upload_files(submission)
            else:
                extValue = get_source(self.request,
                                      'json',
                                      'input',
                                      'submission')
                if not extValue:
                    msg = _(u"No submission source was specified")
                    raise_json_error(self.request,
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': msg,
                                     },
                                     None)
                extValue = extValue.read()
                extValue = read_input_data(extValue, self.request)
                submission = self.readCreateUpdateContentObject(creator,
                                                                externalValue=extValue)
                submission = read_multipart_sources(submission, self.request)

            result = component.getMultiAdapter((self.request, submission),
                                               IExceptionResponse)
        except HTTPCreated as e:
            result = e  # valid response
        except HTTPException:
            logger.exception("HTTP Error while submitting assignment")
            raise
        except Exception as e:
            logger.exception("Error while submitting assignment")
            exc_info = sys.exc_info()
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': str(e),
                                 'code': e.__class__.__name__
                             },
                             exc_info[2])
        notify(UserProgressUpdatedEvent(self.context,
                                        creator,
                                        self.course))
        return result


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             name=ASSESSMENT_PRACTICE_SUBMISSION,
             request_method='POST')
class AssignmentPracticeSubmissionPostView(AssignmentSubmissionPostView):
    """
    A practice assignment submission view that will submit/grade results
    but not persist.
    """

    METADATA_ATTEMPT_VALIDATION = False

    def _validate_submission(self):
        pass

    def _do_call(self):
        try:
            return super(AssignmentPracticeSubmissionPostView, self)._do_call()
        finally:
            self.request.environ['nti.commit_veto'] = 'abort'


class AbstractSubmissionBulkFileDownloadView(AbstractAuthenticatedView):
    """
    An abstract view that provides capabilities for downloading
    submitted assignment file-submissions.
    """

    def _get_course(self, unused_context):
        return None

    def _string(self, val, sub=''):
        if val:
            val = val.replace(' ', sub)
        return val

    def _get_context_name(self):
        context = self.context
        result = getattr(context, 'title', context.__name__)
        result = self._string(result, '_')
        return result or 'assignment'

    def _get_filename_base(self, course):
        """
        Subclasses should override to return the base filename;
        that is, the name of the file excluding the extension.
        """
        pass

    def _get_filename(self, course):
        base_name = self._get_filename_base(course)
        suffix = '.zip'
        result = '%s%s' % (base_name, suffix)
        # strip out any high characters
        result = result.encode('ascii', 'ignore')
        return result

    @classmethod
    def _precondition(cls, unused_context, unused_request, unused_remoteUser):
        return False

    def _get_username_filename_part(self, principal):
        user = User.get_entity(principal.id)
        profile = IUserProfile(user)
        realname = profile.realname or ''
        realname = realname.replace(' ', '_')
        username = replace_username(user.username)
        result = username
        if realname:
            result = '%s-%s' % (username, realname)
        return result

    def _save_files(self, principal, item, zipfile):
        # Hmm, if they don't submit or submit in different orders,
        # numbers won't work. We need to canonicalize this to the
        # assignment order.
        for sub_num, sub_part in enumerate(item.Submission.parts or ()):
            for q_num, q_part in enumerate(sub_part.questions or ()):
                for qp_num, qp_part in enumerate(q_part.parts or ()):
                    if IQResponse.providedBy(qp_part):
                        qp_part = qp_part.value
                    if IFile.providedBy(qp_part):
                        fn_part = self._get_username_filename_part(principal)
                        full_filename = self._submission_filename(item,
                                                                  fn_part,
                                                                  sub_num,
                                                                  q_num,
                                                                  qp_num,
                                                                  qp_part)
                        lastModified = qp_part.lastModified
                        date_time = datetime.utcfromtimestamp(lastModified)
                        info = ZipInfo(full_filename,
                                       date_time=date_time.timetuple())
                        info.compress_type = ZIP_DEFLATED
                        zipfile.writestr(info, qp_part.data)

    def _submission_filename(self, unused_item, fn_part, sub_num, q_num, qp_num, qp_part):
        return "%s-%s-%s-%s-%s" % (fn_part,
                                   sub_num,
                                   q_num,
                                   qp_num,
                                   qp_part.filename)

    def _save_assignment_submissions(self, zipfile, assignment, course, enrollments):
        assignment_id = assignment.__name__
        did_save = False

        for record in enrollments.iter_enrollments():
            principal = IUser(record, None)
            if principal is None:  # dup enrollment ?
                continue
            # TODO: Is this correct? What do we do for multiple submissions?
            history_item = get_most_recent_history_item(principal, course, assignment_id)
            if history_item is None:
                continue  # No submission for this assignment
            self._save_files(principal, history_item, zipfile)
            did_save = True
        return did_save

    def _save_submissions(self, course, enrollments, zipfile):
        """
        Subclasses should override to save the relevant assignment file-submissions.
        """
        pass

    def __call__(self):
        context = self.request.context
        request = self.request

        if not self._precondition(context, request, self.remoteUser):
            raise hexc.HTTPForbidden()

        buf = BytesIO()
        zipfile = ZipFile(buf, 'w')
        course = self._get_course(context)
        enrollments = ICourseEnrollments(course)

        self._save_submissions(course, enrollments, zipfile)
        # We could raise a 404 here, but do not currently until clients
        # could handle it, preferring to return an empty zip.

        zipfile.close()
        buf.seek(0)
        self.request.response.body = buf.getvalue()
        filename = self._get_filename(course)
        response = self.request.response
        response.content_encoding = 'identity'
        response.content_type = 'application/zip; charset=UTF-8'
        response.content_disposition = 'attachment; filename="%s"' % filename
        return response

@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             # permission=ACT_DOWNLOAD_GRADES, # handled manually because it's
             # on the course, not the context
             request_method='GET',
             name='BulkFilePartDownload')
class AssignmentSubmissionBulkFileDownloadView(AbstractSubmissionBulkFileDownloadView):
    """
    A view that returns a ZIP file containing all
    the files submitted by any student in the course forz
    any file part in the given assignment.

    The ZIP has the following structure::

    <student-username>/
            <part-num>/
                    <question-num>/
                            <submitted-file-name>

    For the convenience of people that don't understand directories
    and how to work with them, this structure is flattened
    using dashes.

    .. note:: An easy extension to this would be to accept
            a query param giving a list of usernames to include.

    .. note:: The current implementation does not stream;
            the entire ZIP is buffered (potentially in memory) before being
            transmitted. Streaming while building a ZIP is somewhat
            complicated in the ZODB/WSGI combination. It may be possible
            to do something with app_iter and stream in \"chunks\".
    """

    def _get_course(self, context):
        result = get_course_from_request(self.request)
        if result is None:
            # Ok, pick the first course we find.
            result = get_course_from_evaluation(context, self.remoteUser, exc=True)
        return result

    def _get_course_name(self, course):
        entry = ICourseCatalogEntry(course, None)
        if entry is not None:
            base_name = entry.ProviderUniqueID
            base_name = self._string(base_name)
        if not base_name:
            base_name = course.__name__
        return base_name

    def _get_filename_base(self, course):
        base_name = self._get_course_name(course)
        assignment_name = self._get_context_name()
        return '%s_%s' % (base_name, assignment_name)

    @classmethod
    def _precondition(cls, context, request, remoteUser):
        return assignment_download_precondition(context, request, remoteUser)

    def _save_submissions(self, course, enrollments, zipfile):
        assignment = self.request.context
        return self._save_assignment_submissions(zipfile, assignment, course, enrollments)


@view_config(route_name="objects.generic.traversal",
             context=ICourseInstance,
             renderer='rest',
             request_method='GET',
             name=VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD)
class CourseAssignmentSubmissionBulkFileDownloadView(AbstractSubmissionBulkFileDownloadView):
    """
    A view that returns a ZIP file containing all
    the files submitted by any student in the course for
    any file part in all assignments in the course.

    The ZIP has the following structure::

    <assignment-name>/
            <student-username>/
                    <part-num>/
                            <question-num>/
                                    <submitted-file-name>

    For the convenience of people who don't understand directories
    and how to work with them, the part of the structure
    following the assignment-name is flattened using dashes.

    .. note:: An easy extension to this would be to accept
            a query param giving a list of usernames to include.

    .. note:: The current implementation does not stream;
            the entire ZIP is buffered (potentially in memory) before being
            transmitted. Streaming while building a ZIP is somewhat
            complicated in the ZODB/WSGI combination. It may be possible
            to do something with app_iter and stream in \"chunks\".
    """

    def _get_course(self, context):
        return context

    def _get_filename_base(self, unused_course):
        return self._get_context_name()

    def _submission_filename(self, item, fn_part, sub_num, q_num, qp_num, qp_part):
        # Prepend the assignment directory to the submission filename
        filename = super(CourseAssignmentSubmissionBulkFileDownloadView, self)._submission_filename(item,
                                                                                                    fn_part,
                                                                                                    sub_num,
                                                                                                    q_num,
                                                                                                    qp_num,
                                                                                                    qp_part)
        return os.path.join(self._current_directory_name, filename)

    def _get_assignments(self, course):
        assignments = get_course_assignments(course)
        return filter(assignment_download_precondition, assignments)

    @classmethod
    def _precondition(cls, context, request, remoteUser):
        return course_assignments_download_precondition(context, request, remoteUser)

    def _save_submissions(self, course, enrollments, zipfile):
        slugify_unique = UniqueSlugify(separator='_')
        assignments = self._get_assignments(course)
        did_save = False
        for assignment in assignments:
            # Directory names need to be unique
            self._current_directory_name = slugify_unique(assignment.title)
            did_save_assigment = self._save_assignment_submissions(zipfile, assignment, course, enrollments)
            did_save = did_save or did_save_assigment
        self._current_directory_name = None
        return did_save


@view_defaults(route_name="objects.generic.traversal",
               renderer='rest',
               context=IUsersCourseAssignmentHistory,
               permission=nauth.ACT_READ,
               request_method='GET')
class AssignmentHistoryGetView(AbstractAuthenticatedView):
    """
    Students can view their assignment history as ``path/to/course/AssignmentHistory``
    """

    def __call__(self):
        history = self.request.context
        return history


@component.adapter(IUsersCourseAssignmentHistory, IRequest)
class AssignmentHistoryRequestTraversable(ContainerTraversable):

    def __init__(self, context, unused_request):
        ContainerTraversable.__init__(self, context)

    def traverse(self, name, further_path):
        if name == 'lastViewed':
            # Stop traversal here so our named view
            # gets to handle this
            raise LocationError(self._container, name)
        return ContainerTraversable.traverse(self, name, further_path)


@view_config(route_name="objects.generic.traversal",
             renderer='rest',
             context=IUsersCourseAssignmentHistory,
             # We handle permissioning manually, not sure
             # what context this is going to be in
             # permission=nauth.ACT_UPDATE,
             request_method='PUT',
             name='lastViewed')
class AssignmentHistoryLastViewedPutView(AbstractAuthenticatedView,
                                         ModeledContentUploadRequestUtilsMixin):
    """
    Given an assignment history, a student can change the lastViewed
    by PUTting to it.

    Currently this is a named view; if we wanted to use the field traversing
    support, we would need to register an ITraversable subclass for this object
    that extends _AbstractExternalFieldTraverser.
    """

    inputClass = Number

    def _do_call(self):
        if self.request.context.owner != self.remoteUser:
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Only the student can set lastViewed."),
                             },
                             None)
        ext_input = self.readInput()
        history = self.request.context
        self.request.context.lastViewed = ext_input
        return history


@view_config(route_name="objects.generic.traversal",
             context=IUsersCourseAssignmentHistoryItem,
             renderer='rest',
             permission=nauth.ACT_DELETE,
             request_method='DELETE')
class AssignmentHistoryItemDeleteView(UGDDeleteView):

    def _do_delete_object(self, theObject):
        del theObject.__parent__[theObject.__name__]
        return theObject
