#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment submission/history

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import sys
from io import BytesIO
from numbers import Number
from datetime import datetime

from zipfile import ZIP_DEFLATED

from zipfile import ZipFile
from zipfile import ZipInfo

from zope import component

from zope.container.traversal import ContainerTraversable

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

from nti.app.assessment._submission import get_source
from nti.app.assessment._submission import check_upload_files
from nti.app.assessment._submission import read_multipart_sources

from nti.app.assessment.common.evaluations import is_assignment_available
from nti.app.assessment.common.evaluations import get_course_from_evaluation

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.utils import replace_username
from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import assignment_download_precondition

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error
from nti.app.externalization.internalization import read_input_data

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.base.interfaces import IFile

from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.dataserver.users.interfaces import IUserProfile


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             request_method='POST')
class AssignmentSubmissionPostView(AbstractAuthenticatedView,
                                   ModeledContentUploadRequestUtilsMixin):
    """
    Students can POST to the assignment to create their submission.
    """

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

    def _validate_submission(self):
        creator = self.remoteUser
        course = get_course_from_request(self.request)
        if course is None:
            logger.warn('Submission for assessment without course context (user=%s)',
                        creator)
            msg = _(u"Submission for assessment without course context")
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': msg,
                             },
                             None)

        if not is_assignment_available(self.context, course=course, user=creator):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Assignment is not available."),
                             },
                             None)

    def _do_call(self):
        creator = self.remoteUser
        try:
            self._validate_submission()
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

    def _validate_submission(self):
        pass

    def _do_call(self):
        try:
            return super(AssignmentPracticeSubmissionPostView, self)._do_call()
        finally:
            self.request.environ['nti.commit_veto'] = 'abort'


@view_config(route_name="objects.generic.traversal",
             context=IQAssignment,
             renderer='rest',
             # permission=ACT_DOWNLOAD_GRADES, # handled manually because it's
             # on the course, not the context
             request_method='GET',
             name='BulkFilePartDownload')
class AssignmentSubmissionBulkFileDownloadView(AbstractAuthenticatedView):
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

    def _string(self, val, sub=''):
        if val:
            val = val.replace(' ', sub)
        return val

    def _get_course_name(self, course):
        entry = ICourseCatalogEntry(course, None)
        if entry is not None:
            base_name = entry.ProviderUniqueID
            base_name = self._string(base_name)
        if not base_name:
            base_name = course.__name__
        return base_name

    def _get_assignment_name(self):
        context = self.context
        result = getattr(context, 'title', context.__name__)
        result = self._string(result, '_')
        return result or 'assignment'

    def _get_filename(self, course):
        base_name = self._get_course_name(course)
        assignment_name = self._get_assignment_name()
        suffix = '.zip'
        result = '%s_%s%s' % (base_name, assignment_name, suffix)
        # strip out any high characters
        result = result.encode('ascii', 'ignore')
        return result

    @classmethod
    def _precondition(cls, context, request, remoteUser):
        return assignment_download_precondition(context, request, remoteUser)

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
                        full_filename = "%s-%s-%s-%s-%s" % (fn_part,
                                                            sub_num,
                                                            q_num,
                                                            qp_num,
                                                            qp_part.filename)
                        lastModified = qp_part.lastModified
                        date_time = datetime.utcfromtimestamp(lastModified)
                        info = ZipInfo(full_filename,
                                       date_time=date_time.timetuple())
                        info.compress_type = ZIP_DEFLATED
                        zipfile.writestr(info, qp_part.data)

    def __call__(self):
        context = self.request.context
        request = self.request

        if not self._precondition(context, request, self.remoteUser):
            raise hexc.HTTPForbidden()

        # We're assuming we'll find some submitted files.
        # What should we do if we don't?
        assignment_id = context.__name__

        course = self._get_course(context)
        enrollments = ICourseEnrollments(course)

        buf = BytesIO()
        zipfile = ZipFile(buf, 'w')
        for record in enrollments.iter_enrollments():
            principal = IUser(record, None)
            if principal is None:  # dup enrollment ?
                continue
            assignment_history = component.getMultiAdapter((course, principal),
                                                           IUsersCourseAssignmentHistory)
            history_item = assignment_history.get(assignment_id)
            if history_item is None:
                continue  # No submission for this assignment
            self._save_files(principal, history_item, zipfile)

        zipfile.close()
        buf.seek(0)
        self.request.response.body = buf.getvalue()
        filename = self._get_filename(course)
        response = self.request.response
        response.content_encoding = 'identity'
        response.content_type = 'application/zip; charset=UTF-8'
        response.content_disposition = 'attachment; filename="%s"' % filename
        return response


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
