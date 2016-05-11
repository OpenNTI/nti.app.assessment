#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import six
import copy
import uuid
from urlparse import urlparse

from html5lib import HTMLParser
from html5lib import treebuilders

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.i18n import translate

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import make_evaluation_ntiid
from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import get_evaluation_containment

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IQAvoidSolutionCheck

from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import get_safe_source_filename
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.app.contentfile import validate_sources

from nti.app.products.courseware import ASSETS_FOLDER

from nti.app.products.courseware.resources.utils import get_course_filer
from nti.app.products.courseware.resources.utils import is_internal_file_link
from nti.app.products.courseware.resources.utils import get_file_from_external_link

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH
from nti.app.publishing.views import PublishView
from nti.app.publishing.views import UnpublishView

from nti.appserver.dataserver_pyramid_views import GenericGetView

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.assignment import QAssignmentPart

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQHint
from nti.assessment.interfaces import IQPart
from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQAssignmentPart
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer

from nti.assessment.question import QQuestionSet

from nti.common.maps import CaseInsensitiveDict

from nti.common.property import Lazy

from nti.contentfile.interfaces import IContentBaseFile

from nti.contentfragments.html import _html5lib_tostring

from nti.contentfragments.interfaces import IHTMLContentFragment

from nti.contenttypes.courses.interfaces import NTI_COURSE_FILE_SCHEME

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.coremetadata.interfaces import IPublishable

from nti.dataserver import authorization as nauth
from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified

from nti.site.hostpolicy import get_host_site

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID

def get_html_content_fields(context):
	result = []
	if IQHint.providedBy(context):
		result.append((context, 'value'))
	elif IQPart.providedBy(context):
		result.append((context, 'content'))
		result.append((context, 'explanation'))
		for hint in context.hints or ():
			result.extend(get_html_content_fields(hint))
	elif 	IQAssignment.providedBy(context) \
		or	IQuestion.providedBy(context) \
		or	IQPoll.providedBy(context):
		result.append((context, 'content'))
		for part in context.parts or ():
			result.extend(get_html_content_fields(part))
	elif IQuestionSet.providedBy(context) or IQSurvey.providedBy(context):
		for question in context.questions or ():
			result.extend(get_html_content_fields(question))
	elif IQAssignmentPart.providedBy(context):
		result.append((context, 'content'))
		result.extend(get_html_content_fields(context.question_set))
	elif IQAssignment.providedBy(context):
		result.append((context, 'content'))
		for parts in context.parts or ():
			result.extend(get_html_content_fields(parts))
	return tuple(result)

def _associate(model, source):
	if IContentBaseFile.providedBy(source):
		source.add_association(model)

def _handle_evaluation_content(context, user, model, sources=None):
	filer = get_course_filer(context, user)
	sources = sources if sources is not None else {}
	for obj, name in get_html_content_fields(model):
		value = getattr(obj, name, None)
		if value and filer != None:
			modified = False
			value = IHTMLContentFragment(value)
			parser = HTMLParser(tree=treebuilders.getTreeBuilder("lxml"),
								namespaceHTMLElements=False)
			doc = parser.parse(value)
			for e in doc.iter():
				attrib = e.attrib
				href = attrib.get('href')
				if not href:
					continue
				elif is_internal_file_link(href):
					source = get_file_from_external_link(href)
					_associate(model, source)
				elif href.startswith(NTI_COURSE_FILE_SCHEME):
					# save resource in filer
					path = urlparse(href).path
					path, name = os.path.split(path)
					source = sources.get(name)
					if source is None:
						source = filer.get(name, path)
						if source is not None:
							_associate(model, source)
							location = filer.get_external_link(source)
						else:
							logger.error("Missing multipart-source %s", href)
							continue
					else:
						path = path or ASSETS_FOLDER
						key = get_safe_source_filename(source, name)
						location = filer.save(key, source, overwrite=False,
											  bucket=path, context=model)
					# change href
					attrib['href'] = location
					modified = True

			if modified:
				value = _html5lib_tostring(doc, sanitize=False)
				setattr(obj, name, value)
	return model

def indexed_iter():
	return list()

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

def validate_internal(theObject, course, request):
	validate_savepoints(theObject, course, request)
	validate_submissions(theObject, course, request)

def register_context(context, site_name=None):
	ntiid = context.ntiid
	provided = iface_of_assessment(context)
	site_name = get_resource_site_name(context) if not site_name else site_name
	registry = get_host_site(site_name).getSiteManager()
	if registry.queryUtility(provided, name=ntiid) is None:
		registerUtility(registry, context, provided, name=ntiid)
	# process 'children'
	if IQEvaluationItemContainer.providedBy(context):
		for item in context.Items or ():
			register_context(item, site_name)
	elif IQAssignment.providedBy(context):
		for item in context.iter_question_sets():
			register_context(item, site_name)
			
class EvaluationMixin(object):

	@Lazy
	def course(self):
		result = find_interface(self.context, ICourseInstance, strict=False)
		return result

	@Lazy
	def has_submissions(self):
		return has_submissions(self.context, self.course)

	@Lazy
	def has_savepoints(self):
		return has_savepoints(self.context, self.course)

	@Lazy
	def _extra(self):
		return str(uuid.uuid4()).split('-')[0]

	def get_ntiid(self, context):
		if isinstance(context, six.string_types):
			result = context
		else:
			result = getattr(context, 'ntiid', None)
		return result
	
	def store_evaluation(self, obj, course, user, check_solutions=True):
		provided = iface_of_assessment(obj)
		evaluations = ICourseEvaluations(course)
		obj.ntiid = ntiid = make_evaluation_ntiid(provided, user, extra=self._extra)
		lifecycleevent.created(obj)
		try:
			# XXX mark to avoid checking solutions
			if not check_solutions: 
				interface.alsoProvides(obj, IQAvoidSolutionCheck)
			# XXX mark as editable before storing so proper validation is done
			interface.alsoProvides(obj, IQEditableEvaluation)
			evaluations[ntiid] = obj # gain intid
		finally:
			# XXX remove temp interface
			if not check_solutions:
				interface.noLongerProvides(obj, IQAvoidSolutionCheck)
		return obj

	def get_registered_evaluation(self, obj, course):
		ntiid = self.get_ntiid(obj)
		evaluations = ICourseEvaluations(course)
		if ntiid in evaluations:  # replace
			obj = evaluations[ntiid]
		else:
			provided = iface_of_assessment(obj)
			obj = component.queryUtility(provided, name=ntiid)
		return obj

	def is_new(self, context):
		ntiid = self.get_ntiid(context)
		return not ntiid

	def handle_question(self, theObject, course, user, check_solutions=True):
		if self.is_new(theObject):
			theObject = self.store_evaluation(theObject, course, user, check_solutions)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Question does not exists."),
								u'code': 'QuestionDoesNotExists',
							 },
							 None)
		return theObject

	def handle_poll(self, theObject, course, user):
		if self.is_new(theObject):
			theObject = self.store_evaluation(theObject, course, user, False)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Poll does not exists."),
								u'code': 'PollDoesNotExists',
							 },
							 None)
		return theObject

	def handle_question_set(self, theObject, course, user, check_solutions=True):
		if self.is_new(theObject):
			questions = indexed_iter()
			for question in theObject.questions or ():
				question = self.handle_question(question, course, user, check_solutions)
				questions.append(question)
			theObject.questions = questions
			theObject = self.store_evaluation(theObject, course, user)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("QuestionSet does not exists."),
								u'code': 'QuestionSetDoesNotExists',
							 },
							 None)
		
		return theObject

	def handle_survey(self, theObject, course, user):
		if self.is_new(theObject):
			questions = indexed_iter()
			for poll in theObject.questions or ():
				poll = self.handle_poll(poll, course, user)
				questions.append(poll)
			theObject.questions = questions
			theObject = self.store_evaluation(theObject, course, user)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Survey does not exists."),
								u'code': 'SurveyDoesNotExists',
							 },
							 None)
		return theObject

	def handle_assignment_part(self, part, course, user):
		question_set = self.handle_question_set(part.question_set,
												course, 
												user)
		part.question_set = question_set
		return part

	def handle_assignment(self, theObject, course, user):
		if self.is_new(theObject):
			parts = indexed_iter()
			for part in theObject.parts or ():
				part = self.handle_assignment_part(part, course, user)
				parts.append(part)
			theObject.parts = parts
			theObject = self.store_evaluation(theObject, course, user)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Assignment does not exists."),
								u'code': 'AssignmentDoesNotExists',
							 },
							 None)
		return theObject

	def handle_evaluation(self, theObject, course, sources, user):
		if IQuestion.providedBy(theObject):
			result = self.handle_question(theObject, course, user)
		elif IQPoll.providedBy(theObject):
			result = self.handle_poll(theObject, course, user)
		elif IQuestionSet.providedBy(theObject):
			result = self.handle_question_set(theObject, course, user)
		elif IQSurvey.providedBy(theObject):
			result = self.handle_survey(theObject, course, user)
		elif IQAssignment.providedBy(theObject):
			result = self.handle_assignment(theObject, course, user)
		else:
			result = theObject
	
		# course is the evaluation home	
		theObject.__home__ = course
		# parse content fields and load sources
		_handle_evaluation_content(course, user, result, sources)
		# always register
		register_context(result)
		return result

	def post_update_check(self, contentObject, externalValue):
		pass

	def auto_complete_questionset(self, context, externalValue):
		questions = indexed_iter() if not context.questions else context.questions
		items = externalValue.get(ITEMS)
		for item in items or ():
			question = self.get_registered_evaluation(item, self.course)
			if not IQuestion.providedBy(question):
				msg = translate(_("Question ${ntiid} does not exists.",
								mapping={'ntiid': item}))
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': msg,
									u'code': 'QuestionDoesNotExists',
								 },
								 None)
			else:
				questions.append(question)
		context.questions = questions
		
	def auto_complete_survey(self, context, externalValue):
		questions = indexed_iter() if not context.questions else context.questions
		items = externalValue.get(ITEMS)
		for item in items or ():
			poll = self.get_registered_evaluation(item, self.course)
			if not IQPoll.providedBy(poll):
				msg = translate(_("Question ${ntiid} does not exists.",
								mapping={'ntiid': item}))
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': msg,
									u'code': 'QuestionDoesNotExists',
								 },
								 None)
			else:
				questions.append(poll)
		context.questions = questions

	def auto_complete_assignment(self, context, externalValue):
		parts = indexed_iter() if not context.parts else context.parts
		if not parts:  # auto create part
			parts.append(QAssignmentPart())
		for part in parts:
			if part.question_set is None: # auto create question set
				part.question_set = QQuestionSet()
			self.auto_complete_questionset(part.question_set, externalValue)		
		context.parts = parts

# POST views

@view_config(context=ICourseEvaluations)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='POST',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationsPostView(EvaluationMixin, UGDPostView):

	content_predicate = IQEvaluation.providedBy

	def postCreateObject(self, context, externalValue):
		if IQuestionSet.providedBy(context) and not context.questions:
			self.auto_complete_questionset(context, externalValue)
		elif IQSurvey.providedBy(context) and not context.questions:
			self.auto_complete_survey(context, externalValue)
		elif 	IQAssignment.providedBy(context) \
			and (not context.parts or any(p.question_set is None for p in context.parts)):
			self.auto_complete_assignment(context, externalValue)
				
	def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
		contentObject, _, externalValue = \
				self.performReadCreateUpdateContentObject(user=creator,
													 	  search_owner=search_owner,
													 	  externalValue=externalValue,
													 	  deepCopy=True)
		self.postCreateObject(contentObject, externalValue)
		sources = get_all_sources(self.request)
		return contentObject, sources

	def _do_call(self):
		creator = self.remoteUser
		evaluation, sources = self.readCreateUpdateContentObject(creator, search_owner=False)
		evaluation.creator = creator.username # use username
		interface.alsoProvides(evaluation, IQEditableEvaluation)

		# validate sources if available
		if sources:
			validate_sources(self.remoteUser, evaluation, sources)
		evaluation = self.handle_evaluation(evaluation, self.course, sources, creator)
		self.request.response.status_int = 201
		return evaluation

# PUT views

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='PUT',
			   permission=nauth.ACT_CONTENT_EDIT)
class EvaluationPutView(EvaluationMixin, UGDPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the object definition.")

	def readInput(self, value=None):
		result = UGDPutView.readInput(self, value=value)
		result.pop('ntiid', None)
		result.pop(NTIID, None)
		return result

	def _check_object_constraints(self, obj, externalValue):
		super(EvaluationPutView, self)._check_object_constraints(obj, externalValue)
		if not IQEditableEvaluation.providedBy(obj):
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': self.OBJ_DEF_CHANGE_MSG,
								u'code': 'CannotChangeObjectDefinition',
							 },
							 None)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		originalSource = copy.deepcopy(externalValue)
		result = UGDPutView.updateContentObject(self,
												contentObject,
												externalValue,
												set_id=set_id,
												notify=False)
		self.post_update_check(contentObject, originalSource)
		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result.model, sources)

		self.handle_evaluation(contentObject, self.course, sources, self.remoteUser)
		# validate changes - subscribers
		notifyModified(contentObject, originalSource)
		return result

@view_config(route_name='objects.generic.traversal',
			 context=IQuestion,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class QuestionPutView(EvaluationPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the question definition.")

	def _check_object_constraints(self, obj, externalValue):
		super(QuestionPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('parts')
		if parts and self.has_submissions:
			if len(parts) != len(self.context.parts):
				raise_json_error(
					self.request,
					hexc.HTTPUnprocessableEntity,
					{
						u'message': _("Cannot change the number of question parts"),
						u'code': 'CannotChangeObjectDefinition',
					},
					None)

@view_config(route_name='objects.generic.traversal',
			 context=IQuestionSet,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class QuestionSetPutView(EvaluationPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the question set definition.")

	def _check_object_constraints(self, obj, externalValue):
		super(QuestionSetPutView, self)._check_object_constraints(obj, externalValue)
		course = find_interface(obj, ICourseInstance, strict=False)
		questions = externalValue.get('questions')
		if questions:  # check for submissions
			validate_submissions(obj, course, self.request)

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			items = originalSource.get(ITEMS)
			if items: # list of ntiids
				contentObject.questions = indexed_iter() # reset
				self.auto_complete_questionset(contentObject, originalSource)

class NewAndLegacyPutView(EvaluationMixin, AssessmentPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the object definition.")

	def _check_object_constraints(self, obj, externalValue):
		super(NewAndLegacyPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('parts')
		if parts:
			if not IQEditableEvaluation.providedBy(obj):
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': self.OBJ_DEF_CHANGE_MSG,
									u'code': 'CannotChangeObjectDefinition',
								 },
								 None)
			else:
				course = find_interface(obj, ICourseInstance, strict=False)
				validate_submissions(obj, course, self.request)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		originalSource = copy.deepcopy(externalValue)
		result = AssessmentPutView.updateContentObject(self,
													   contentObject,
													   externalValue,
													   set_id=set_id,
													   notify=False)
		self.post_update_check(contentObject, originalSource)
		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result.model, sources)

		if IQEditableEvaluation.providedBy(contentObject):
			self.handle_evaluation(contentObject, self.course, sources, self.remoteUser)
		# validate changes, subscribers
		notifyModified(contentObject, originalSource)
		return result

@view_config(route_name='objects.generic.traversal',
			 context=IQPoll,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class PollPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Poll will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Poll will become unavailable. Please confirm.')

	def _check_object_constraints(self, obj, externalValue):
		super(PollPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('parts')
		if parts:
			if not IQEditableEvaluation.providedBy(obj):
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': _("Cannot change the poll definition."),
									u'code': 'CannotChangeObjectDefinition',
								 },
								 None)
			elif self.has_submissions:
				if len(parts) != len(self.context.parts):
					raise_json_error(
							self.request,
							hexc.HTTPUnprocessableEntity,
							{
								u'message': _("Cannot change the number of poll parts"),
								u'code': 'CannotChangeObjectDefinition',
							},
							None)

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

	def _check_object_constraints(self, obj, externalValue):
		super(SurveyPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('questions')
		if parts:
			if not IQEditableEvaluation.providedBy(obj):
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': _("Cannot change the survey definition."),
									u'code': 'CannotChangeObjectDefinition',
								 },
								 None)
			else:
				course = find_interface(obj, ICourseInstance, strict=False)
				validate_submissions(obj, course, self.request)

	def validate(self, contentObject, externalValue, courses=()):
		if not IPublishable.providedBy(contentObject) or contentObject.is_published():
			super(SurveyPutView, self).validate(contentObject, externalValue, courses)

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			items = originalSource.get(ITEMS)
			if items: # list of ntiids
				contentObject.questions = indexed_iter() # reset
				self.auto_complete_survey(contentObject, originalSource)

@view_config(route_name='objects.generic.traversal',
			 context=IQAssignment,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class AssignmentPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Assignment will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Assignment will become unavailable. Please confirm.')

	def _check_object_constraints(self, obj, externalValue):
		super(AssignmentPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('parts')
		if parts:
			if not IQEditableEvaluation.providedBy(obj):
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': _("Cannot change the assignment definition."),
									u'code': 'CannotChangeObjectDefinition',
								 },
								 None)
			else:
				course = find_interface(obj, ICourseInstance, strict=False)
				validate_submissions(obj, course, self.request)

	def validate(self, contentObject, externalValue, courses=()):
		if not IPublishable.providedBy(contentObject) or contentObject.is_published():
			super(AssignmentPutView, self).validate(contentObject, externalValue, courses)

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			items = originalSource.get(ITEMS)
			if items: # list of ntiids
				for qset in contentObject.iter_question_sets(): # reset
					qset.questions = indexed_iter()
				self.auto_complete_assignment(contentObject, originalSource)

# DELETE views

def delete_evaluation(evaluation, course=None):
	# delete from evaluations
	course = find_interface(evaluation, ICourseInstance, strict=False)
	evaluations = ICourseEvaluations(course)
	del evaluations[evaluation.ntiid]
	evaluation.__home__ = None 

	# remove from registry
	provided = iface_of_assessment(evaluation)
	registered = component.queryUtility(provided, name=evaluation.ntiid)
	if registered is not None:
		site_name = get_resource_site_name(course)
		registry = get_host_site(site_name).getSiteManager()
		unregisterUtility(registry, provided=provided, name=evaluation.ntiid)

@view_config(route_name="objects.generic.traversal",
			 context=IQEvaluation,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class EvaluationDeleteView(UGDDeleteView):

	def _check_internal(self, theObject):
		if not IQEditableEvaluation.providedBy(theObject):
			raise hexc.HTTPForbidden(_("Cannot delete legacy object."))
		course = find_interface(theObject, ICourseInstance, strict=False)
		validate_internal(theObject, course, self.request)
		containment = get_evaluation_containment(theObject.ntiid)
		if containment:
			raise_json_error(
						self.request,
						hexc.HTTPUnprocessableEntity,
						{
							u'message': _("Cannot delete a contained object."),
							u'code': 'CannotDeleteEvaluation',
						},
						None)

	def _do_delete_object(self, theObject):
		self._check_internal(theObject)
		delete_evaluation(theObject)
		return theObject

# Publish views

def publish_context(context, site_name=None):
	# publish
	if not context.is_published():
		context.publish()
	# register utility
	register_context(context, site_name)
	# process 'children'
	if IQEvaluationItemContainer.providedBy(context):
		for item in context.Items or ():
			publish_context(item, site_name)
	elif IQAssignment.providedBy(context):
		for item in context.iter_question_sets():
			publish_context(item, site_name)

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
 			   name=VIEW_PUBLISH,
			   permission=nauth.ACT_UPDATE,
			   request_method='POST')
class EvaluationPublishView(PublishView):

	def _do_provide(self, context):
		if IQEditableEvaluation.providedBy(context):
			publish_context(context)

# Unublish views

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
 			   name=VIEW_UNPUBLISH,
			   permission=nauth.ACT_UPDATE,
			   request_method='POST')
class EvaluationUnpublishView(UnpublishView):

	def _do_provide(self, context):
		if IQEditableEvaluation.providedBy(context):
			course = find_interface(context, ICourseInstance, strict=False)
			validate_submissions(context, course, self.request)
			# unpublish
			super(EvaluationUnpublishView, self)._do_provide(context)

# get views

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IQEvaluation,
			 request_method='GET',
			 permission=nauth.ACT_READ)
class EvaluationGetView(GenericGetView):

	def __call__(self):
		result = GenericGetView.__call__(self)
		# XXX Check than only editors can have access 
		# to unpublished evalutations
		if 		IQEditableEvaluation.providedBy(result) \
			and not result.is_published() \
			and not has_permission(ACT_CONTENT_EDIT, result, self.request):
			raise hexc.HTTPForbidden()
		return result
