#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
import copy
import uuid

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.i18n import translate

from zope.event import notify

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import validate_auto_grade
from nti.app.assessment.common import make_evaluation_ntiid
from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import get_evaluation_containment
from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import validate_submissions
from nti.app.assessment.evaluations.utils import import_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IQAvoidSolutionCheck

from nti.app.assessment.views.view_mixins import AssessmentPutView
from nti.app.assessment.views.view_mixins import StructuralValidationMixin

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import BatchingUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.contentfile import validate_sources

from nti.app.products.courseware.views.view_mixins import IndexedRequestMixin
from nti.app.products.courseware.views.view_mixins import DeleteChildViewMixin
from nti.app.products.courseware.views.view_mixins import AbstractChildMoveView

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH

from nti.app.publishing.views import PublishView
from nti.app.publishing.views import UnpublishView

from nti.appserver.dataserver_pyramid_views import GenericGetView

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import TIMED_ASSIGNMENT_MIME_TYPE

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer

from nti.assessment.interfaces import QuestionInsertedInContainerEvent
from nti.assessment.interfaces import QuestionRemovedFromContainerEvent

from nti.assessment.interfaces import QuestionMovedEvent

from nti.common.maps import CaseInsensitiveDict

from nti.common.property import Lazy

from nti.contenttypes.courses.interfaces import ICourseInstance

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
LINKS = StandardExternalFields.LINKS
NTIID = StandardExternalFields.NTIID

VERSION = u'Version'

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

class EvaluationMixin(StructuralValidationMixin):

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
		"""
		Finish initalizing new evaluation object and store persistently.
		"""
		provided = iface_of_assessment(obj)
		evaluations = ICourseEvaluations(course)
		obj.ntiid = ntiid = make_evaluation_ntiid(provided, user, extra=self._extra)
		obj.creator = getattr(user, 'username', user)
		lifecycleevent.created(obj)
		try:
			# XXX mark to avoid checking solutions
			if not check_solutions:
				interface.alsoProvides(obj, IQAvoidSolutionCheck)
			# XXX mark as editable before storing so proper validation is done
			interface.alsoProvides(obj, IQEditableEvaluation)
			evaluations[ntiid] = obj  # gain intid
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
		# Make sure we handle any parts that may have been
		# added to our existing or new assignment.
		parts = indexed_iter()
		for part in theObject.parts or ():
			part = self.handle_assignment_part(part, course, user)
			parts.append(part)
		theObject.parts = parts
		if self.is_new(theObject):
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
		import_evaluation_content(result, context=course, user=user, sources=sources)
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
		# Clients are expected to create parts/qsets as needed.
		parts = indexed_iter() if not context.parts else context.parts
		for part in parts:
			if part.question_set is not None:
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

	def readInput(self, value=None):
		result = UGDPostView.readInput(self, value=value)
		for key in (VERSION,):
			result.pop(key, None)
			result.pop(key.lower(), None)
		return result

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
		evaluation.creator = creator.username  # use username
		interface.alsoProvides(evaluation, IQEditableEvaluation)

		# validate sources if available
		if sources:
			validate_sources(self.remoteUser, evaluation, sources)
		evaluation = self.handle_evaluation(evaluation, self.course, sources, creator)
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
							IndexedRequestMixin):
	"""
	Creates a question at the given index path, if supplied.
	Otherwise, append to our context.
	"""

	def readInput(self, value=None):
		result = ModeledContentUploadRequestUtilsMixin.readInput(self, value=value)
		for key in (VERSION,):
			result.pop(key, None)
			result.pop(key.lower(), None)
		return result

	def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
		contentObject, _, externalValue = \
				self.performReadCreateUpdateContentObject(user=creator,
													 	  search_owner=search_owner,
													 	  externalValue=externalValue,
													 	  deepCopy=True)
		sources = get_all_sources(self.request)
		return contentObject, sources

	def _get_new_question(self):
		creator = self.remoteUser
		new_question, sources = self.readCreateUpdateContentObject(creator, search_owner=False)
		if sources:
			validate_sources(self.remoteUser, new_question, sources)
		new_question = self.handle_evaluation(new_question, self.course, sources, creator)
		return new_question

	def _get_courses(self, context):
		result = find_interface(context, ICourseInstance, strict=False)
		return get_courses(result)

	def _validate(self):
		# Make sure our auto_grade status still holds.
		courses = self._get_courses( self.context )
		assignments = get_assignments_for_evaluation_object( self.context )
		for course in courses or ():
			for assignment in assignments or ():
				validate_auto_grade(assignment, course)

	def __call__(self):
		self._pre_flight_validation( self.context, structural_change=True )
		index = self._get_index()
		question = self._get_new_question()
		self.context.insert(index, question)
		notify(QuestionInsertedInContainerEvent(self.context, question, index))
		logger.info('Inserted new question (%s)', question.ntiid)
		# validate changes
		self._validate()
		self.request.response.status_int = 201
		return question

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
		for key in (NTIID, VERSION):
			result.pop(key, None)
			result.pop(key.lower(), None)
		return result

	def _check_object_constraints(self, obj, externalValue):
		super(EvaluationPutView, self)._check_object_constraints(obj, externalValue)
		self._pre_flight_validation( obj, externalValue )
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
		self._pre_flight_validation( obj, externalValue )

@view_config(route_name='objects.generic.traversal',
			 context=IQuestionSet,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class QuestionSetPutView(EvaluationPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the question set definition.")

	def _check_object_constraints(self, obj, externalValue):
		super(QuestionSetPutView, self)._check_object_constraints(obj, externalValue)
		self._pre_flight_validation( obj, externalValue )

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			items = originalSource.get(ITEMS)
			if items:  # list of ntiids
				contentObject.questions = indexed_iter()  # reset
				self.auto_complete_questionset(contentObject, originalSource)

class NewAndLegacyPutView(EvaluationMixin, AssessmentPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the object definition.")
	LEGACY_EDITABLE_FIELDS = ('available_for_submission_beginning',
							  'available_for_submission_ending')

	def _check_object_constraints(self, obj, externalValue):
		editing_keys = set( externalValue.keys() )
		if 		not IQEditableEvaluation.providedBy(obj) \
			and editing_keys - set( self.LEGACY_EDITABLE_FIELDS ):
			# Cannot edit content backed assessment objects (except
			# for available dates).
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': self.OBJ_DEF_CHANGE_MSG,
								u'code': 'CannotChangeObjectDefinition',
							 },
							 None)
		super(NewAndLegacyPutView, self)._check_object_constraints(obj, externalValue)
		self._pre_flight_validation( obj, externalValue )

	def readInput(self, value=None):
		result = AssessmentPutView.readInput(self, value=value)
		for key in (VERSION,):
			result.pop(key, None)
			result.pop(key.lower(), None)
		return result

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
	OBJ_DEF_CHANGE_MSG = _("Cannot change the poll definition.")

@view_config(route_name='objects.generic.traversal',
			 context=IQSurvey,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class SurveyPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Survey will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Survey will become unavailable. Please confirm.')
	OBJ_DEF_CHANGE_MSG = _("Cannot change the survey definition.")

	def _check_object_constraints(self, obj, externalValue):
		super(SurveyPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('questions')
		if parts:
			self._validate_structural_edits()

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			items = originalSource.get(ITEMS)
			if items:  # list of ntiids
				contentObject.questions = indexed_iter()  # reset
				self.auto_complete_survey(contentObject, originalSource)

@view_config(route_name='objects.generic.traversal',
			 context=IQAssignment,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class AssignmentPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Assignment will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Assignment will become unavailable. Please confirm.')
	OBJ_DEF_CHANGE_MSG = _("Cannot change the assignment definition.")

	def _check_object_constraints(self, obj, externalValue):
		super(AssignmentPutView, self)._check_object_constraints(obj, externalValue)
		parts = externalValue.get('parts')
		if parts:
			self._validate_structural_edits()

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			items = originalSource.get(ITEMS)
			if items:  # list of ntiids
				for qset in contentObject.iter_question_sets():  # reset
					qset.questions = indexed_iter()
				self.auto_complete_assignment(contentObject, originalSource)

	def _index(self, item):
		lifecycleevent.modified(item)

	def _re_register(self, context, old_iface, new_iface):
		"""
		Unregister the context under the given old interface and register
		under the given new interface.
		"""
		ntiid = context.ntiid
		site_name = get_resource_site_name(context)
		registry = get_host_site(site_name).getSiteManager()
		registerUtility(registry, context, provided=new_iface, name=ntiid, event=False)
		unregisterUtility(registry, provided=old_iface, name=ntiid, event=False)
		# Make sure we re-index.
		self._index(context)

	def _transform_to_timed(self, contentObject, max_time_allowed):
		"""
		Transform from a regular assignment to a timed assignment.
		"""
		interface.alsoProvides(contentObject, IQTimedAssignment)
		contentObject.maximum_time_allowed = max_time_allowed
		contentObject.mimeType = contentObject.mime_type = TIMED_ASSIGNMENT_MIME_TYPE
		self._re_register(contentObject, IQAssignment, IQTimedAssignment)

	def _transform_to_untimed(self, contentObject):
		"""
		Transform from a timed assignment to a regular assignment.
		"""
		interface.noLongerProvides(contentObject, IQTimedAssignment)
		contentObject.mimeType = contentObject.mime_type = ASSIGNMENT_MIME_TYPE
		contentObject.maximum_time_allowed = None
		self._re_register(contentObject, IQTimedAssignment, IQAssignment)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		# Must toggle types first (if necessary) before calling super; so
		# everything validates.
		if 'maximum_time_allowed' in externalValue:
			# The client passed us something; see if we are going to/from timed assignment.
			max_time_allowed = externalValue.get('maximum_time_allowed')
			if 		max_time_allowed \
				and not IQTimedAssignment.providedBy(contentObject):
				self._transform_to_timed(contentObject, max_time_allowed)
			elif	max_time_allowed is None \
				and IQTimedAssignment.providedBy(contentObject):
				self._transform_to_untimed(contentObject)

		result = super(AssignmentPutView, self).updateContentObject(contentObject, externalValue,
																	   set_id, notify)
		return result

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
class EvaluationDeleteView(UGDDeleteView,
						   EvaluationMixin):

	def _check_internal(self, theObject):
		if not IQEditableEvaluation.providedBy(theObject):
			raise hexc.HTTPForbidden(_("Cannot delete legacy object."))
		self._pre_flight_validation( self.context, structural_change=True )
		# TODO: Need this still?
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
		notify(QuestionRemovedFromContainerEvent(self.context, item, index))

	def _validate(self):
		self._pre_flight_validation( self.context, structural_change=True )

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
		# to unpublished evaluations.
		if 		IQEditableEvaluation.providedBy(result) \
			and not result.is_published() \
			and not has_permission(ACT_CONTENT_EDIT, result, self.request):
			raise hexc.HTTPForbidden()
		return result

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

	def _validate_parents(self, *args, **kwargs):
		# We do not have to do super validation since we're only
		# moving within question set.
		self._pre_flight_validation( self.context, structural_change=True )
		if not IQEditableEvaluation.providedBy(self.context):
			raise_json_error(
						self.request,
						hexc.HTTPUnprocessableEntity,
						{
							u'message': _("Cannot move within an uneditable question set."),
							u'code': 'CannotMoveEvaluations',
						},
						None)
