#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import copy

from zope import component
from zope import interface
from zope import lifecycleevent

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import make_evaluation_ntiid

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.assessment.views import MessageFactory as _

from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.app.contentfile import validate_sources

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQEditable
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation

from nti.common.maps import CaseInsensitiveDict

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.coremetadata.interfaces import IPublishable

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

#
# def _handle_multipart(context, user, model, sources):
# 	provided = ICourseDiscussion
# 	filer = get_course_filer(context, user)
# 	for name, source in sources.items():
# 		if name in provided:
# 			# remove existing
# 			location = getattr(discussion, name, None)
# 			if location:
# 				filer.remove(location)
# 			# save a in a new file
# 			key = get_safe_source_filename(source, name)
# 			location = filer.save(key, source, overwrite=False,
# 								  bucket=ASSETS_FOLDER, context=discussion)
# 			setattr(discussion, name, location)

@view_config(context=ICourseEvaluations)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='GET',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationsGetView(AbstractAuthenticatedView, BatchingUtilsMixin):

	_DEFAULT_BATCH_SIZE = 50
	_DEFAULT_BATCH_START = 0

	def _get_mimeTypes(self):
		params = CaseInsensitiveDict(self.request.params)
		result = params.get('accept') or params.get('mimeType')
		result = set(result.split(',')) if result else ()
		return result or ()

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context
		result.lastModified = self.context.lastModified
		mimeTypes = self._get_mimeTypes()
		items = result[ITEMS] = []
		if mimeTypes:
			items.extend(x for x in self.context.values() if x.mimeType in mimeTypes)
		else:
			items.extend(self.context.values())

		result['TotalItemCount'] = len(items)
		self._batch_items_iterable(result, items)
		result['ItemCount'] = len(result[ITEMS])
		return result

def validate_submissions(theObject, course, request):
	if has_submissions(theObject, course):
		raise_json_error(request,
						 hexc.HTTPUnprocessableEntity,
						 {
							u'message': _("Object has submissions."),
							u'code': 'ObjectHasSubmissions',
						 },
						 None)

def validate_savepoints(theObject, course, request):
	if has_savepoints(theObject, course):
		raise_json_error(request,
						 hexc.HTTPUnprocessableEntity,
						 {
							u'message': _("Object has savepoints"),
							u'code': 'ObjectHasSavepoints',
						 },
						 None)

def valdiate_internal(theObject, course, request):
	validate_savepoints(theObject, course, request)
	validate_submissions(theObject, course, request)

class EvaluationMixin(object):

	def get_register_evaluation(self, obj, course, user):
		ntiid = getattr(obj, 'ntiid', None)
		provided = iface_of_assessment(obj)
		evaluations = ICourseEvaluations(course)
		if not ntiid:  # new object
			obj.ntiid = make_evaluation_ntiid(provided, user)
			lifecycleevent.created(obj)
			evaluations[ntiid] = obj
		elif ntiid in evaluations:  # replace
			obj = evaluations[ntiid]
		else:
			obj = component.queryUtility(provided, ntiid=ntiid)
		return obj

	def handle_question(self, question, course, sources, user):
		question = self.get_register_evaluation(question, course, user)
		if question is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Question does not exists."),
								u'code': 'QuestionDoesNotExists',
							 },
							 None)
		return question

	def handle_questionset(self, theObject, course, sources, user):
		theObject = self.get_register_evaluation(theObject, course, user)
		if theObject is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("QuestionSet does not exists."),
								u'code': 'QuestionSetDoesNotExists',
							 },
							 None)
		questions = []
		for question in theObject.questions or ():
			question = self.handle_question(question, course, sources, user)
			questions.append(questions)
		theObject.questions = questions

	def handle_evaluation(self, theObject, course, sources, user):
		if IQuestion.providedBy(theObject):
			result = self.handle_question(theObject, course, sources, user)
		elif IQuestionSet.providedBy(theObject):
			result = self.handle_question(theObject, course, sources, user)
		else:
			result = theObject
		return result

# POST views

@view_config(context=ICourseEvaluations)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='POST',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationsPostView(EvaluationMixin, UGDPostView):

	content_predicate = IQEvaluation.providedBy

	def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
		contentObject = self.doReadCreateUpdateContentObject(creator=creator,
															 search_owner=search_owner,
															 externalValue=externalValue)
		sources = get_all_sources(self.request)
		return contentObject, sources

	def _do_call(self):
		creator = self.remoteUser
		evaluation, sources = self.readCreateUpdateContentObject(creator, search_owner=False)
		evaluation.creator = creator.username
		interface.alsoProvides(evaluation, IQEditable)

		course = find_interface(self.context, ICourseInstance, strict=False)
		evaluation = self.handle_evaluation(evaluation, course, sources, creator)
		self.request.response.status_int = 201
		return evaluation

# PUT views

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='PUT',
			   permission=nauth.ACT_CONTENT_EDIT)
class EvaluationPutView(EvaluationMixin, UGDPutView):

	def readInput(self, value=None):
		result = UGDPutView.readInput(self, value=value)
		result.pop('ntiid', None)
		result.pop(NTIID, None)
		return result

	def _check_object_constraints(self, obj, externalValue):
		super(EvaluationPutView, self)._check_object_constraints(obj, externalValue)
		if not IQEditable.providedBy(obj):
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Cannot change the object definition."),
								u'code': 'CannotChangeObjectDefinition',
							 },
							 None)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		originalSource = copy.copy(externalValue)
		result = UGDPutView.updateContentObject(self,
												contentObject,
												externalValue,
												set_id=set_id,
												notify=False)

		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result.model, sources)
			# _handle_multipart(self.context, self.remoteUser, self.context, sources)
		notifyModified(contentObject, originalSource)
		return result

@view_config(route_name='objects.generic.traversal',
			 context=IQuestion,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class QuestionPutView(EvaluationPutView):

	def _check_object_constraints(self, obj, externalValue):
		super(QuestionPutView, self)._check_object_constraints(obj, externalValue)
		course = find_interface(obj, ICourseInstance, strict=False)
		parts = externalValue.get('parts')
		if parts:  # check for submissions
			validate_submissions(obj, course, self.request)

class NewAndLegacyPutView(EvaluationMixin, AssessmentPutView):

	def _check_object_constraints(self, obj, externalValue):
		super(NewAndLegacyPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('parts')
		if parts:
			if not IQEditable.providedBy(obj):
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': _("Cannot change the object definition."),
									u'code': 'CannotChangeObjectDefinition',
								 },
								 None)
			else:
				course = find_interface(obj, ICourseInstance, strict=False)
				validate_submissions(obj, course, self.request)

@view_config(route_name='objects.generic.traversal',
			 context=IQPoll,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class PollPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Poll will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Poll will become unavailable. Please confirm.')

	def validate(self, contentObject, externalValue, courses=()):
		if not IPublishable.providedBy(contentObject) or contentObject.is_published():
			super(PollPutView, self).validate(contentObject, externalValue, courses)

@view_config(route_name='objects.generic.traversal',
			 context=IQSurvey,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class SurveyPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Survey will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Survey will become unavailable. Please confirm.')

	def validate(self, contentObject, externalValue, courses=()):
		if not IPublishable.providedBy(contentObject) or contentObject.is_published():
			super(SurveyPutView, self).validate(contentObject, externalValue, courses)

@view_config(route_name='objects.generic.traversal',
			 context=IQAssignment,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class AssignmentPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Assignment will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Assignment will become unavailable. Please confirm.')

	def validate(self, contentObject, externalValue, courses=()):
		if not IPublishable.providedBy(contentObject) or contentObject.is_published():
			super(AssignmentPutView, self).validate(contentObject, externalValue, courses)

# DELETE views

@view_config(route_name="objects.generic.traversal",
			 context=IQEvaluation,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class EvaluationDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		if not IQEditable.providedBy(theObject):
			raise hexc.HTTPForbidden(_("Cannot delete legacy object."))
		course = find_interface(theObject, ICourseInstance, strict=False)
		valdiate_internal(theObject, course, self.request)
		del theObject.__parent__[theObject.__name__]
		return theObject
