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

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.interface.common.idatetime import IDateTime

from zope.security.interfaces import IPrincipal

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment._assessment import move_user_assignment_from_course_to_course

from nti.app.assessment.common import index_course_package_assessments

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint

from nti.app.assessment.views import tx_string
from nti.app.assessment.views import parse_catalog_entry

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.views import CourseAdminPathAdapter

from nti.assessment.interfaces import IQSubmittable
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserverFolder

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               name='MoveUserAssignments')
class MoveUserAssignmentsView(AbstractAuthenticatedView,
                              ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            values = super(MoveUserAssignmentsView, self).readInput(value)
        else:
            values = self.request.params
        return CaseInsensitiveDict(values)

    def _do_move(self, user, source, target):
        return move_user_assignment_from_course_to_course(user, source, target)

    def __call__(self):
        values = self.readInput()
        source = parse_catalog_entry(values, names=("source", "origin"))
        target = parse_catalog_entry(values, names=("target", "dest"))
        if source is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                'message': _(u"Invalid source NTIID."),
                             },
                             None)
        if target is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                'message': _(u"Invalid target NTIID."),
                             },
                             None)
        if source == target:
            msg = _(u"Source and Target courses are the same")
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                'message': msg,
                             },
                             None)

        source = ICourseInstance(source)
        target = ICourseInstance(target)
        usernames = values.get('usernames') or values.get('username')
        if usernames:
            usernames = usernames.split(',')
        else:
            usernames = tuple(ICourseEnrollments(source).iter_principals())

        result = LocatedExternalDict()
        items = result[ITEMS] = {}
        for username in usernames:
            user = User.get_user(username)
            if user is None or not IUser.providedBy(user):
                logger.info("User %s does not exists", username)
                continue
            moved = self._do_move(user, source, target)
            items[username] = sorted(moved)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result


@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               permission=nauth.ACT_NTI_ADMIN,
               name='SetCourseDatePolicy')
class SetCourseDatePolicy(AbstractAuthenticatedView,
                          ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        result = super(SetCourseDatePolicy, self).readInput(value)
        return CaseInsensitiveDict(result)

    def _get_datetime(self, x=None):
        for func in (float, int):
            try:
                value = func(x)
                return datetime.fromtimestamp(value)
            except (ValueError, TypeError):
                pass
        try:
            return IDateTime(x)
        except Exception:
            pass
        return None

    def _process_row(self, course, evaluation, beginning=None, ending=None):
        course = ICourseInstance(find_object_with_ntiid(course or ''), None)
        evaluation = component.queryUtility(IQSubmittable,
                                            name=evaluation or '')
        if course is None or evaluation is None:
            return False

        dates = []
        for x in (beginning, ending):
            if x:
                x = self._get_datetime(x)
                if x is None:
                    return False
            dates.append(x)

        context = IQAssessmentDateContext(course)
        for idx, key in enumerate(('available_for_submission_beginning',
                                   'available_for_submission_ending')):
            value = dates[idx]
            if value is not None:
                context.set(evaluation.ntiid, key, value)
        return True

    def __call__(self):
        values = self.readInput()
        sources = get_all_sources(self.request, None)
        if sources:
            for name, source in sources.items():
                rdr = csv.reader(source)
                for idx, row in enumerate(rdr):
                    if len(row) < 3:
                        logger.error("[%s]. Invalid entry at line %s",
                                     name, idx)
                        continue
                    course = row[0]
                    evaluation = row[1]
                    beginning = row[2]
                    ending = row[3] if len(row) >= 4 else None
                    if not self._process_row(course, evaluation, beginning, ending):
                        logger.error("[%s]. Invalid entry at line %s",
                                     name, idx)
        else:
            evaluation = values.get('evaluation') \
                      or values.get('assignment') \
                      or values.get('assesment') \
                      or values.get('nttid')
            if not self._process_row(values.get('course') or values.get('context'),
                                     evaluation,
                                     values.get('beginning') or values.get('start'),
                                     values.get('ending') or values.get('end')):
                logger.error("Invalid input data %s", values)
                raise_json_error(self.request,
                                 hexc.HTTPUnprocessableEntity,
                                 {
                                    'message': _(u"Invalid input data."),
                                 },
                                 None)
        return hexc.HTTPNoContent()


@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               name='RemoveMatchedSavePoints')
class RemovedMatchedSavePointsView(AbstractAuthenticatedView,
                                   ModeledContentUploadRequestUtilsMixin):

    """
    Remove savepoint for already submitted assignment(s)
    """

    def _do_call(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = {}
        catalog = component.getUtility(ICourseCatalog)
        for entry in catalog.iterCatalogEntries():
            course = ICourseInstance(entry)
            enrollments = ICourseEnrollments(course)
            for record in enrollments.iter_enrollments():
                principal = record.Principal
                history = component.queryMultiAdapter((course, principal),
                                                      IUsersCourseAssignmentHistory)
                savepoint = component.queryMultiAdapter((course, principal),
                                                        IUsersCourseAssignmentSavepoint)
                if not savepoint or not history:
                    continue
                for assignmentId in set(history.keys()):  # snapshot
                    if assignmentId in savepoint:
                        savepoint._delitemf(assignmentId, event=False)
                        assignments = items.setdefault(principal.username, [])
                        assignments.append(assignmentId)
        return result


@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               request_method='GET',
               name='UnmatchedSavePoints')
class UnmatchedSavePointsView(AbstractAuthenticatedView):

    def __call__(self):
        catalog = component.getUtility(ICourseCatalog)
        params = CaseInsensitiveDict(self.request.params)
        entry = parse_catalog_entry(params)
        if entry is not None:
            entries = (entry,)
        else:
            entries = catalog.iterCatalogEntries()

        response = self.request.response
        response.content_encoding = 'identity'
        response.content_type = 'text/csv; charset=UTF-8'
        response.content_disposition = 'attachment; filename="report.csv"'

        stream = BytesIO()
        writer = csv.writer(stream)
        header = ['course', 'username', 'assignment']
        writer.writerow(header)

        for entry in entries:
            ntiid = entry.ntiid
            course = ICourseInstance(entry)
            enrollments = ICourseEnrollments(course)
            for record in enrollments.iter_enrollments():
                principal = record.Principal
                if IPrincipal(principal, None) is None:
                    continue

                history = component.queryMultiAdapter((course, principal),
                                                      IUsersCourseAssignmentHistory)

                savepoint = component.queryMultiAdapter((course, principal),
                                                        IUsersCourseAssignmentSavepoint)
                if not savepoint:
                    continue

                for assignmentId in set(savepoint.keys()):  # snapshot
                    if assignmentId not in history or ():
                        row_data = [ntiid, principal.username, assignmentId]
                        writer.writerow([tx_string(x) for x in row_data])

        stream.flush()
        stream.seek(0)
        response.body_file = stream
        return response


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               request_method='POST',
               name='RemoveCourseEvaluations')
class RemoveCourseEvaluationsView(AbstractAuthenticatedView):

    def __call__(self):
        course = ICourseInstance(self.context)
        evaluations = ICourseEvaluations(course, None)
        if evaluations:
            evaluations.clear()
        return hexc.HTTPNoContent()


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               request_method='POST',
               name='ReindexCoursePackageAssessments')
class ReindexCoursePackageAssessmentsView(AbstractAuthenticatedView):
    """
    Indexes the package assessments for the course context. Useful
    if we have stale data tying assessment items to a course.
    """

    def __call__(self):
        course = ICourseInstance(self.context)
        result = LocatedExternalDict()
        count = index_course_package_assessments(course)
        result['IndexedCount'] = count
        return result

