#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=too-many-function-args

import csv
from io import BytesIO
from datetime import datetime

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from requests.structures import CaseInsensitiveDict

import six

import transaction

from zope import component

from zope.container.interfaces import INameChooser

from zope.intid.interfaces import IIntIds

from zope.interface.common.idatetime import IDateTime

from zope.security.interfaces import IPrincipal

from nti.app.assessment import MessageFactory as _

from nti.app.assessment._assessment import move_user_assignment_from_course_to_course

from nti.app.assessment.common.containers import index_course_package_assessments

from nti.app.assessment.history import UsersCourseAssignmentHistoryItemContainer

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadata
from nti.app.assessment.interfaces import ICourseAssignmentAttemptMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemContainer

from nti.app.assessment.evaluations.utils import delete_evaluation

from nti.app.assessment.common.history import delete_all_evaluation_data

from nti.app.assessment.metadata import UsersCourseAssignmentAttemptMetadataItem

from nti.app.assessment.subscribers import delete_course_user_data

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

from nti.dataserver.metadata.index import get_metadata_catalog

from nti.dataserver.users.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

logger = __import__('logging').getLogger(__name__)


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
            # pylint: disable=too-many-function-args
            usernames = tuple(ICourseEnrollments(source).iter_principals())

        result = LocatedExternalDict()
        items = result[ITEMS] = {}
        for username in usernames:
            user = User.get_user(username)
            if not IUser.providedBy(user):
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
        except Exception:  # pylint: disable=broad-except
            pass
        return None

    def _process_row(self, course, evaluation, beginning=None, ending=None):
        course = find_object_with_ntiid(course or '')
        course = ICourseInstance(course, None)
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
                # pylint: disable=too-many-function-args
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
            # pylint: disable=too-many-function-args
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
                        # pylint: disable=protected-access
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
            # pylint: disable=too-many-function-args
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


@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               request_method='POST',
               name='RemoveGhostSubmissions')
class RemoveGhostSubmissionsView(AbstractAuthenticatedView):

    interfaces = (IUsersCourseInquiries,
                  IUsersCourseAssignmentHistories,
                  IUsersCourseAssignmentSavepoints,
                  ICourseAssignmentAttemptMetadata)

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = {}
        catalog = component.getUtility(ICourseCatalog)
        for entry in catalog.iterCatalogEntries():
            usernames = set()
            course = ICourseInstance(entry)
            for iface in self.interfaces:
                container = iface(course)
                usernames.update(container.keys())
            for username in usernames:
                user = User.get_user(username)
                if not IUser.providedBy(user):
                    for iface in self.interfaces:
                        container = iface(course)
                        try:
                            del container[username]
                        except KeyError:
                            pass
                    items.setdefault(username, [])
                    items[username].append(entry.ntiid)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               request_method='POST',
               name='RemoveCourseEvaluations')
class RemoveCourseEvaluationsView(AbstractAuthenticatedView):

    def __call__(self):
        count = 0
        course = ICourseInstance(self.context)
        evaluations = IQEvaluations(course, None)
        if evaluations:
            logger.warning("Removing %s evaluation(s)", len(evaluations))
            for item in tuple(evaluations.values()):  # mutating
                count += 1
                if IQSubmittable.providedBy(item):
                    delete_all_evaluation_data(item)
                delete_evaluation(item)
                if count % 50 == 0:
                    transaction.savepoint(optimistic=True)
            # clear container
            # pylint: disable=too-many-function-args
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
        result[TOTAL] = result['IndexedCount'] = count
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               request_method='POST',
               name='RemoveUserCourseEvaluationData')
class RemoveUserCourseEvaluationDataView(AbstractAuthenticatedView,
                                         ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        result = ModeledContentUploadRequestUtilsMixin.readInput(self, value)
        return CaseInsensitiveDict(result)

    def __call__(self):
        values = self.readInput()
        usernames = values.get('username') or values.get('usernames')
        if isinstance(usernames, six.string_types):
            usernames = usernames.split(',')
        if not usernames:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Must specify a username."),
                             },
                             None)
        course = ICourseInstance(self.context)
        for username in usernames:
            logger.warning("Deleting course evaluation data for user %s", username)
            delete_course_user_data(course, username)
        return hexc.HTTPNoContent()


@view_config(context=IDataserverFolder)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_NTI_ADMIN,
               name='FixBrokenHistoryItems')
class FixBrokenHistoryItemsView(AbstractAuthenticatedView):

    """
    Loop through courses and look for history items that should be in
    history item containers. These are items that are not in the metadata
    catalog for some reason, so reindex them.

    Also ensure we create a meta item for this history item.
    These are items missing in evolve45.
    """

    def get_user(self, obj):
        result = obj.creator
        if not IUser.providedBy(result):
            result = User.get_user(result)
        if result is None:
            logger.warn('History item without a creator (%s)', obj)
        return result

    def legacy_seed(self, user, intids):
        return intids.getId(user)

    def create_meta_attempt(self, user, item, intids, assignment_ntiid, entry_ntiid):
        course = find_interface(item, ICourseInstance, strict=False)
        if course is None:
            logger.info('Cannot find course for item (%s)', item)
            return
        user_meta = component.queryMultiAdapter((course, user),
                                                IUsersCourseAssignmentAttemptMetadata)
        item_container = user_meta.get_or_create(assignment_ntiid)
        if len(item_container) < 1:
            # Only do this if this is our only attempt
            attempt = UsersCourseAssignmentAttemptMetadataItem()
            attempt.containerId = assignment_ntiid
            attempt.Seed = self.legacy_seed(user, intids)
            # All floats (int duration)
            # Legacy submissions will not have durations
            attempt.Duration = duration = getattr(item.Submission, 'CreatorRecordedEffortDuration', -1)
            attempt.StartTime = float(item.createdTime - duration if duration > 0 else 0)
            # Don't toggle these fields if savepoint
            if IUsersCourseAssignmentHistoryItem.providedBy(item):
                attempt.SubmitTime = float(item.createdTime)
                attempt.HistoryItem = item
            logger.info('Creating meta attempt (%s) (%s) (%s)',
                        user.username, entry_ntiid, assignment_ntiid)
            item_container.add_attempt(attempt)

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = {}
        intids = component.getUtility(IIntIds)
        metadata_catalog = get_metadata_catalog()
        index = metadata_catalog['mimeType']
        MIME_TYPES = ('application/vnd.nextthought.assessment.userscourseassignmenthistoryitem',)
        item_intids = index.apply({'any_of': MIME_TYPES})

        catalog = component.getUtility(ICourseCatalog)
        for entry in catalog.iterCatalogEntries():
            course = ICourseInstance(entry)
            entry_ntiid = entry.ntiid
            entry_results = []
            histories = IUsersCourseAssignmentHistories(course)
            for user_history in histories.values():
                user = self.get_user(user_history)
                if user is None:
                    continue
                for assignment_ntiid, history_item in user_history.items():
                    if IUsersCourseAssignmentHistoryItemContainer.providedBy(history_item):
                        # We have a container, assure each history_item has a meta attempt
                        # associated with it
                        for item in history_item.values():
                            self.create_meta_attempt(user, item, intids, assignment_ntiid, entry_ntiid)
                        continue
                    # Ensure meta attempt
                    self.create_meta_attempt(user, history_item, intids, assignment_ntiid, entry_ntiid)
                    # Now update our history item container structure
                    logger.info('Moving to history item container (%s) (%s) (%s)',
                                user, entry_ntiid, assignment_ntiid)
                    submission_container = user_history._delitemf(assignment_ntiid, event=False)
                    if not IUsersCourseAssignmentHistoryItemContainer.providedBy(submission_container):
                        submission_container = UsersCourseAssignmentHistoryItemContainer()
                    user_history[assignment_ntiid] = submission_container
                    assert submission_container.__parent__ is not None
                    chooser = INameChooser(submission_container)
                    key = chooser.chooseName('', history_item)
                    submission_container[key] = history_item
                    assert history_item.__parent__ is submission_container
                    entry_results.append({'username': user.username,
                                          'assignment_id': assignment_ntiid})

                    # Assure item is indexed
                    if history_item._ds_intid not in item_intids:
                        metadata_catalog.index_doc(history_item._ds_intid, history_item)
            items[entry_ntiid] = entry_results
        return result
