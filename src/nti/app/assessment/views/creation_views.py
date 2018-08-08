#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import Mapping

from requests.structures import CaseInsensitiveDict

from zope import interface

from zope.cachedescriptors.property import Lazy

from zope.event import notify as event_notify

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_COPY_EVALUATION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS

from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.common.policy import validate_auto_grade
from nti.app.assessment.common.policy import get_auto_grade_policy

from nti.app.assessment.common.utils import get_courses

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import get_package_from_request

from nti.app.assessment.views.view_mixins import VERSION
from nti.app.assessment.views.view_mixins import EvaluationMixin
from nti.app.assessment.views.view_mixins import ValidateAutoGradeMixin

from nti.app.assessment.views.view_mixins import get_courses_from_assesment

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.contentfile import validate_sources

from nti.app.products.courseware.views.view_mixins import IndexedRequestMixin
from nti.app.products.courseware.views.view_mixins import AbstractChildMoveView

from nti.appserver.ugd_edit_views import UGDPostView

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.assessment.interfaces import QAssessmentPoliciesModified
from nti.assessment.interfaces import QuestionInsertedInContainerEvent

from nti.assessment.interfaces import QuestionMovedEvent

from nti.common.string import is_true

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.externalization.proxy import removeAllProxies

from nti.mimetype.externalization import decorateMimeType

from nti.traversal.traversal import find_interface

OID = StandardExternalFields.OID
ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
MIMETYPE = StandardExternalFields.MIMETYPE
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


@view_config(context=IQEvaluations)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               permission=nauth.ACT_CONTENT_EDIT)
class EvaluationsPostView(EvaluationMixin, UGDPostView):

    content_predicate = IQEvaluation.providedBy

    def readInput(self, value=None):
        result = UGDPostView.readInput(self, value=value)
        [result.pop(x, None) for x in (VERSION, VERSION.lower())]
        return result

    def postCreateObject(self, context, externalValue):
        if IQuestionSet.providedBy(context) and not context.questions:
            self.auto_complete_questionset(context, externalValue)
        elif IQSurvey.providedBy(context) and not context.questions:
            self.auto_complete_survey(context, externalValue)
        elif    IQAssignment.providedBy(context) \
            and (not context.parts or any(p.question_set is None for p in context.parts)):
            self.auto_complete_assignment(context, externalValue)

    def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
        result = self.performReadCreateUpdateContentObject(creator, search_owner,
                                                           externalValue, True)
        contentObject, _, externalValue = result
        self.postCreateObject(contentObject, externalValue)
        sources = get_all_sources(self.request)
        return contentObject, sources

    def _do_call(self):
        creator = self.remoteUser
        evaluation, sources = self.readCreateUpdateContentObject(creator)
        evaluation.creator = creator.username  # use username
        interface.alsoProvides(evaluation, IQEditableEvaluation)
        # validate sources if available
        if sources:
            validate_sources(self.remoteUser, evaluation, sources)
        evaluation = self.handle_evaluation(evaluation, self.composite,
                                            sources, creator)
        self.request.response.status_int = 201
        return evaluation


@view_config(name=VIEW_COPY_EVALUATION)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='POST',
               context=IQEvaluation,
               permission=nauth.ACT_CONTENT_EDIT)
class EvaluationCopyView(AbstractAuthenticatedView, EvaluationMixin):

    @Lazy
    def _container(self):
        if IQEditableEvaluation.providedBy(self.context):
            result = self.composite
        else:
            result = get_course_from_request(self.request) \
                  or get_package_from_request(self.request)
            if result is None:
                result = get_courses_from_assesment(self.context)
                result = result[0]  # fail hard
        return result

    def _prunner(self, ext_obj):
        if isinstance(ext_obj, Mapping):
            for name in (NTIID, OID):
                ext_obj.pop(name, None)
                ext_obj.pop(name.lower(), None)
            for value in ext_obj.values():
                self._prunner(value)
        elif isinstance(ext_obj, (list, tuple, set)):
            for item in ext_obj:
                self._prunner(item)
        return ext_obj

    def __call__(self):
        creator = self.remoteUser
        source = removeAllProxies(self.context)
        # export to external, make sure we add the MimeType
        ext_obj = to_external_object(source, decorate=False)
        decorateMimeType(source, ext_obj)
        ext_obj = self._prunner(ext_obj)
        # create and update
        evaluation = find_factory_for(ext_obj)()
        update_from_external_object(evaluation, ext_obj)
        evaluation.creator = creator.username  # use username
        interface.alsoProvides(evaluation, IQEditableEvaluation)
        evaluation = self.handle_evaluation(evaluation, self._container,
                                            (), creator)
        self.request.response.status_int = 201
        return evaluation


@view_config(route_name='objects.generic.traversal',
             context=IQuestionSet,
             request_method='POST',
             permission=nauth.ACT_CONTENT_EDIT,
             renderer='rest',
             name=VIEW_QUESTION_SET_CONTENTS)
class QuestionSetInsertView(AbstractAuthenticatedView,
                            ModeledContentUploadRequestUtilsMixin,
                            EvaluationMixin,
                            IndexedRequestMixin,
                            ValidateAutoGradeMixin):
    """
    Creates a question at the given index path, if supplied.
    Otherwise, append to our context.
    """

    def readInput(self, value=None):
        result = super(QuestionSetInsertView, self).readInput(value=value)
        [result.pop(x, None) for x in (VERSION, VERSION.lower())]
        return result

    def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
        result = self.performReadCreateUpdateContentObject(creator, search_owner,
                                                           externalValue, True)
        contentObject, _, externalValue = result
        sources = get_all_sources(self.request)
        return contentObject, sources

    def _get_new_question(self):
        creator = self.remoteUser
        externalValue = self.readInput()
        if isinstance(externalValue, Mapping) and MIMETYPE not in externalValue:
            # They're giving us an NTIID, find the question object.
            ntiid = externalValue.get('ntiid') or externalValue.get(NTIID)
            new_question = self._get_required_question(ntiid)
        else:
            # Else, read in the question.
            new_question, sources = self.readCreateUpdateContentObject(creator)
            if sources:
                validate_sources(self.remoteUser, new_question, sources)
            new_question = self.handle_evaluation(new_question, self.composite,
                                                  sources, creator)
        return new_question

    def _validate(self, params):
        self._validate_auto_grade(params)

    def _do_insert(self, new_question, index):
        self.context.insert(index, new_question)
        logger.info('Inserted new question (%s)', new_question.ntiid)

    def __call__(self):
        self._pre_flight_validation(self.context, structural_change=True)
        params = CaseInsensitiveDict(self.request.params)
        index = self._get_index()
        question = self._get_new_question()
        self._do_insert(question, index)
        factory = QuestionInsertedInContainerEvent
        event_notify(factory(self.context, question, index))
        # validate changes
        self._validate(params)
        self.post_update_check(self.context, {})
        self.request.response.status_int = 201
        return question


@view_config(route_name='objects.generic.traversal',
             context=IQuestionSet,
             request_method='POST',
             permission=nauth.ACT_CONTENT_EDIT,
             renderer='rest',
             name=VIEW_ASSESSMENT_MOVE)
class QuestionSetMoveView(AbstractChildMoveView,
                          EvaluationMixin,
                          ModeledContentUploadRequestUtilsMixin):
    """
    Move the given question within a QuestionSet.
    """

    notify_type = QuestionMovedEvent

    def _remove_from_parent(self, parent, obj):
        return parent.remove(obj)

    def _validate_parents(self, *unused_args, **unused_kwargs):
        # We do not have to do super validation since we're only
        # moving within question set.
        self._pre_flight_validation(self.context, structural_change=True)
        if not IQEditableEvaluation.providedBy(self.context):
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Cannot move within an uneditable question set."),
                                 'code': 'CannotMoveEvaluations',
                             },
                             None)
