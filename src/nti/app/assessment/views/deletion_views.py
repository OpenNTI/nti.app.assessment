#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from requests.structures import CaseInsensitiveDict

from zope.cachedescriptors.property import Lazy

from zope.event import notify as event_notify

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS

from nti.app.assessment.common.evaluations import get_evaluation_containment

from nti.app.assessment.common.history import delete_evaluation_metadata
from nti.app.assessment.common.history import delete_inquiry_submissions
from nti.app.assessment.common.history import delete_evaluation_savepoints
from nti.app.assessment.common.history import delete_evaluation_submissions

from nti.app.assessment.common.submissions import get_all_submissions
from nti.app.assessment.common.submissions import get_all_submissions_courses

from nti.app.assessment.evaluations.utils import delete_evaluation

from nti.app.assessment.views.evaluation_views import EvaluationMixin

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.views.view_mixins import DeleteChildViewMixin

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.assessment.interfaces import QuestionRemovedFromContainerEvent

from nti.common.string import is_true

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.links.links import Link

LINKS = StandardExternalFields.LINKS


@view_config(route_name="objects.generic.traversal",
             context=IQEvaluation,
             renderer='rest',
             permission=nauth.ACT_DELETE,
             request_method='DELETE')
class EvaluationDeleteView(UGDDeleteView,
                           EvaluationMixin,
                           ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            result = super(EvaluationDeleteView, self).readInput(value)
            result = CaseInsensitiveDict(result)
        else:
            result = CaseInsensitiveDict(self.request.params)
        return result

    def _check_editable(self, theObject):
        if not IQEditableEvaluation.providedBy(theObject):
            raise_json_error(self.request,
                             hexc.HTTPForbidden,
                             {
                                 'message': _(u"Cannot delete legacy object."),
                             },
                             None)

    def _check_containment(self, theObject):
        containment = get_evaluation_containment(theObject.ntiid)
        if containment:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Cannot delete a contained object."),
                                 'code': 'CannotDeleteEvaluation',
                             },
                             None)

    def _check_internal(self, theObject):
        self._check_editable(theObject)
        self._pre_flight_validation(self.context, structural_change=True)
        self._check_containment(theObject)

    def _do_delete_object(self, theObject):
        self._check_internal(theObject)
        delete_evaluation(theObject)
        return theObject


@view_config(context=IQPoll)
@view_config(context=IQSurvey)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='DELETE',
               permission=nauth.ACT_DELETE)
class SubmittableDeleteView(EvaluationDeleteView,
                            ModeledContentUploadRequestUtilsMixin):

    @Lazy
    def _is_course(self):
        return ICourseInstance.providedBy(self.composite)

    def _can_delete_contained_data(self, theObject):
        if self._is_course:
            return is_course_instructor(self.course, self.remoteUser) \
                or has_permission(nauth.ACT_NTI_ADMIN, theObject, self.request)
        else:
            return has_permission(nauth.ACT_CONTENT_EDIT, theObject, self.request)

    def _has_submissions(self, theObject):
        for unused in get_all_submissions(theObject):
            return True
        return False

    def _delete_contained_data(self, theObject, course):
        if IQInquiry.providedBy(theObject):
            delete_inquiry_submissions(theObject, course)
        else:
            delete_evaluation_metadata(theObject, course)
            delete_evaluation_savepoints(theObject, course)
            delete_evaluation_submissions(theObject, course)

    def _check_internal(self, theObject):
        self._check_editable(theObject)
        self._check_containment(theObject)

    def _do_delete_object(self, theObject):
        self._check_internal(theObject)
        if not self._can_delete_contained_data(theObject):
            self._pre_flight_validation(theObject, structural_change=True)
        elif self._has_submissions(theObject):
            values = self.readInput()
            force = is_true(values.get('force'))
            if not force:
                links = (
                    Link(self.request.path, rel='confirm',
                         params={'force': True}, method='DELETE'),
                )
                raise_json_error(self.request,
                                 hexc.HTTPConflict,
                                 {
                                     'message': _(u'There are submissions for this evaluation object.'),
                                     'code': 'EvaluationHasSubmissions',
                                     LINKS: to_external_object(links)
                                 },
                                 None)
        for course in get_all_submissions_courses(theObject):
            self._delete_contained_data(theObject, course)
        delete_evaluation(theObject)
        return theObject


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             name=VIEW_QUESTION_SET_CONTENTS,
             context=IQuestionSet,
             request_method='DELETE',
             permission=nauth.ACT_CONTENT_EDIT)
class QuestionSetDeleteChildView(AbstractAuthenticatedView,
                                 EvaluationMixin,
                                 DeleteChildViewMixin):
    """
    A view to delete a child underneath the given context.

    index
            This param will be used to indicate which object should be
            deleted. If the object described by `ntiid` is no longer at
            this index, the object will still be deleted, as long as it
            is unambiguous.

    :raises HTTPConflict if state has changed out from underneath user
    """

    def _get_children(self):
        return self.context.questions

    def _remove(self, item=None, index=None):
        if item is not None:
            self.context.remove(item)
        else:
            self.context.pop(index)
        event_notify(QuestionRemovedFromContainerEvent(self.context, item, index))

    def _validate(self):
        self._pre_flight_validation(self.context, structural_change=True)
