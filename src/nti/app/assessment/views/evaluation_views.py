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

from collections import Mapping

from requests.structures import CaseInsensitiveDict

from zope import interface
from zope import lifecycleevent

from zope.cachedescriptors.property import Lazy

from zope.event import notify as event_notify

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_COPY_EVALUATION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import validate_auto_grade
from nti.app.assessment.common import get_max_time_allowed
from nti.app.assessment.common import get_auto_grade_policy
from nti.app.assessment.common import pre_validate_question_change
from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import delete_evaluation

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import RegradeQuestionEvent

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views.view_mixins import EvaluationMixin
from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.app.assessment.views.view_mixins import get_courses_from_assesment

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.contentfile import validate_sources

from nti.app.products.courseware.views.view_mixins import IndexedRequestMixin
from nti.app.products.courseware.views.view_mixins import AbstractChildMoveView

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView

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
from nti.assessment.interfaces import IQDiscussionAssignment

from nti.assessment.interfaces import QAssessmentPoliciesModified
from nti.assessment.interfaces import QuestionInsertedInContainerEvent
from nti.assessment.interfaces import QuestionRemovedFromContainerEvent

from nti.assessment.interfaces import QuestionMovedEvent

from nti.assessment.question import QQuestionSet

from nti.assessment.randomized.interfaces import IQuestionBank

from nti.assessment.randomized.question import QQuestionBank

from nti.common.string import is_true

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified
from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.externalization.proxy import removeAllProxies

from nti.mimetype.externalization import decorateMimeType

from nti.recorder.record import copy_transaction_history

from nti.traversal.traversal import find_interface

OID = StandardExternalFields.OID
ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
MIMETYPE = StandardExternalFields.MIMETYPE
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

VERSION = u'Version'

# POST views

@view_config(context=IQEvaluations)
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
		evaluation = self.handle_evaluation(evaluation, self.composite, sources, creator)
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
	def course(self):
		if IQEditableEvaluation.providedBy(self.context):
			result = find_interface(self.context, ICourseInstance, strict=False)
		else:
			result = get_course_from_request(self.request)
			if result is None:
				result = get_courses_from_assesment(self.context)[0] # fail hard
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
		evaluation = self.handle_evaluation(evaluation, self.course, (), creator)
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
		externalValue = self.readInput()
		if isinstance(externalValue, Mapping) and MIMETYPE not in externalValue:
			# They're giving us an NTIID, find the question object.
			ntiid = externalValue.get('ntiid') or externalValue.get(NTIID)
			new_question = self._get_required_question( ntiid )
		else:
			# Else, read in the question.
			new_question, sources = self.readCreateUpdateContentObject(creator, search_owner=False)
			if sources:
				validate_sources(self.remoteUser, new_question, sources)
			new_question = self.handle_evaluation(new_question, self.course, sources, creator)
		return new_question

	def _get_courses(self, context):
		result = find_interface(context, ICourseInstance, strict=False)
		return get_courses(result)

	def _disable_auto_grade(self, assignment, course):
		policy = get_auto_grade_policy(assignment, course)
		policy['disable'] = True
		event_notify(QAssessmentPoliciesModified(course, assignment.ntiid, 'auto_grade', False))

	def _validate_auto_grade(self, params):
		"""
		Will validate and raise a challenge if the user wants to disable auto-grading
		and add the non-auto-gradable question to this question set. If overridden,
		we will insert the question and disable auto-grade for all assignments
		referencing this question set.
		"""
		# Make sure our auto_grade status still holds.
		courses = self._get_courses( self.context )
		assignments = get_assignments_for_evaluation_object( self.context )
		override_auto_grade = params.get( 'overrideAutoGrade' ) if params else False
		override_auto_grade = is_true(override_auto_grade)
		is_valid = None
		for course in courses or ():
			for assignment in assignments or ():
				is_valid = validate_auto_grade(assignment, course, self.request,
											   challenge=True, raise_exc=not override_auto_grade)
				if not is_valid and override_auto_grade:
					self._disable_auto_grade( assignment, course )

	def _validate(self, params):
		self._validate_auto_grade( params )

	def _do_insert(self, new_question, index):
		self.context.insert(index, new_question)
		logger.info('Inserted new question (%s)', new_question.ntiid)

	def __call__(self):
		self._pre_flight_validation( self.context, structural_change=True )
		params = CaseInsensitiveDict(self.request.params)
		index = self._get_index()
		question = self._get_new_question()
		self._do_insert( question, index )
		event_notify(QuestionInsertedInContainerEvent(self.context, question, index))
		# validate changes
		self._validate( params )
		self.post_update_check( self.context, {} )
		self.request.response.status_int = 201
		return question

@view_config(route_name='objects.generic.traversal',
			 context=IQuestionSet,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest',
			 name=VIEW_QUESTION_SET_CONTENTS)
class QuestionSetReplaceView( QuestionSetInsertView ):
	"""
	Replaces a question at the given index path.
	"""

	def _get_current_question_at_index(self, index):
		if index is None:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Must give an index to replace a question."),
								u'code': 'QuestionReplaceIndexRequired',
							 },
							 None)
		try:
			old_question = self.context[index]
		except (KeyError, IndexError):
			old_question = None

		params = CaseInsensitiveDict( self.request.params )
		old_ntiid = params.get( 'ntiid' )
		# If they give us ntiid, validate that against our index.
		if 		old_question is None \
			or ( old_ntiid and old_ntiid != old_question.ntiid ):
			raise_json_error(
						self.request,
						hexc.HTTPConflict,
						{
							u'message': _('The question no longer exists at this index.'),
							u'code': 'InvalidQuestionReplaceIndex'
						},
						None)
		return old_question

	def _do_insert(self, new_question, index):
		old_question = self._get_current_question_at_index( index )
		self.context.remove( old_question )
		event_notify(QuestionRemovedFromContainerEvent(self.context, old_question, index))
		self.context.insert( index, new_question )
		logger.info('Replaced question (old=%s) (new=%s)',
					old_question.ntiid, new_question.ntiid)

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

	def _get_post_update_source(self, externalValue):
		return externalValue, copy.deepcopy(externalValue)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		originalSource = copy.deepcopy(externalValue)
		externalValue, update_source = self._get_post_update_source( externalValue )
		result = UGDPutView.updateContentObject(self,
												contentObject,
												externalValue,
												set_id=set_id,
												notify=False)
		self.post_update_check(contentObject, update_source)
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

	def updateContentObject(self, contentObject, externalValue, **kwargs):
		# We need to check our question part changes before we update our content object.
		part_regrades = pre_validate_question_change( contentObject, externalValue )
		result = super( QuestionPutView, self ).updateContentObject(contentObject, externalValue, **kwargs)
		# Only regrade after our content object is updated.
		if part_regrades:
			event_notify(RegradeQuestionEvent(result, part_regrades))
		return result

def _ntiid_only( ext_obj ):
	"""
	Only contains NTIID and no other keys.
	"""
	if not ext_obj:
		return False
	if isinstance(ext_obj, six.string_types):
		return True
	ntiid = ext_obj.get('ntiid') or ext_obj.get(NTIID)
	return ntiid and len( ext_obj ) == 1

def _qset_with_ntiids_only( qset_ext ):
	"""
	Check if our question set *only* has question ntiids.
	"""
	questions = qset_ext.get( 'questions' )
	result = questions and all( _ntiid_only(x) for x in questions )
	return result

def _assignment_part_with_question_set_ntiid_only( part_ext ):
	"""
	Check if our assignment part has *only* an ntiid for the question set.
	"""
	qset = part_ext.get( 'question_set' )
	return _ntiid_only( qset )

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
		super( QuestionSetPutView, self ).post_update_check( contentObject, originalSource )

	def _get_post_update_source(self, externalValue):
		"""
		If our question set just has ntiids, pop from original (in order
		to update without 422ing) and return items for postUpdate.
		"""
		result = dict()
		ntiids_only = _qset_with_ntiids_only( externalValue )
		if ntiids_only:
			result[ITEMS] = externalValue.pop( 'questions' )
		return externalValue, result

	def _update_assignments( self, old_obj, new_obj ):
		"""
		Update all assignments pointing to our question set.
		Any refs in lessons should still work (since we point to ntiid).
		"""
		assignments = get_assignments_for_evaluation_object( old_obj )
		for assignment in assignments:
			for part in assignment.parts or ():
				if part.question_set.ntiid == old_obj.ntiid:
					part.question_set = new_obj

	def _copy_question_set(self, source, target):
		"""
		Copy fields from one question set to the other, also
		copying transaction history and updating assignment refs.
		"""
		target.__parent__ = source.__parent__
		for key, val in source.__dict__.items():
			if not key.startswith('_'):
				setattr( target, key, val )
		copy_transaction_history( source, target )
		self._update_assignments( source, target )

	def _create_new_object( self, obj, course ):
		evaluations = IQEvaluations( course )
		lifecycleevent.created(obj)
		# XXX mark as editable before storing so proper validation is done
		interface.alsoProvides(obj, IQEditableEvaluation)
		evaluations[obj.ntiid] = obj  # gain intid

	def _copy_to_new_type( self, old_obj, new_obj ):
		# XXX: Important to get course here before we mangle context.
		course = self.course
		self._copy_question_set( old_obj, new_obj )
		delete_evaluation( old_obj )
		self._create_new_object( new_obj, course )

	def _transform_to_bank(self, contentObject):
		"""
		Transform from a question set to a question bank.
		"""
		self._pre_flight_validation(contentObject, structural_change=True)
		result = QQuestionBank()
		self._copy_to_new_type( contentObject, result )
		self._re_register( result, IQuestionSet, IQuestionBank )
		return result

	def _transform_to_non_bank(self, contentObject):
		"""
		Transform from a question bank to a regular question set.
		"""
		self._pre_flight_validation(contentObject, structural_change=True)
		result = QQuestionSet()
		self._copy_to_new_type( contentObject, result )
		self._re_register( result, IQuestionBank, IQuestionSet )
		return result

	def _update_bank_status(self, externalValue, contentObject):
		"""
		Determine if our object is transitioning to/from a question bank.
		"""
		if 'draw' in externalValue:
			# The client passed us something; see if we are going to/from question bank.
			draw = externalValue.get('draw')
			if 		draw \
				and not IQuestionBank.providedBy(contentObject):
				contentObject = self._transform_to_bank(contentObject)
			elif	draw is None \
				and IQuestionBank.providedBy(contentObject):
				contentObject = self._transform_to_non_bank(contentObject)
			elif 	draw \
				and contentObject.draw is not None \
				and contentObject.draw != draw:
				# Changing draw counts; validate structurally.
				self._pre_flight_validation(contentObject, structural_change=True)
			# Update our context
			self.context = contentObject
		return self.context

	def updateContentObject(self, contentObject, externalValue, **kwargs):
		# Must do this first to get the actual object we are creating/updating.
		new_contentObject = self._update_bank_status( externalValue, contentObject )

		result = super(QuestionSetPutView, self).updateContentObject(new_contentObject,
																	 externalValue,
																	 **kwargs)
		return result

	def __call__(self):
		# Override to control what is returned.
		super(QuestionSetPutView, self).__call__()
		return self.context

class NewAndLegacyPutView(EvaluationMixin, AssessmentPutView):

	OBJ_DEF_CHANGE_MSG = _("Cannot change the object definition.")

	@Lazy
	def course(self):
		result = find_interface(self.context, ICourseInstance, strict=False)
		return result if result is not None else get_course_from_request()

	@property
	def legacy_editable_fields(self):
		# XXX: We allow toggling public status? This is the only
		# change that may lock the assignment from syncing.
		return ('is_non_public',) + self.policy_keys

	def _require_course(self):
		course = get_course_from_request()
		if course is None:
			raise hexc.HTTPForbidden(_('Must supply course'))
		return course

	def _validate_instructor_edit(self, externalValue):
		"""
		We want to allow instructors to edit their specific course assessment
		policies.
		"""
		course = self._require_course()
		if not is_course_instructor(course, self.remoteUser):
			raise hexc.HTTPForbidden()
		non_policy_edits = bool(set( externalValue.keys() ) - set( self.policy_keys ))
		if non_policy_edits:
			raise hexc.HTTPForbidden(_('Instructors can only edit policy fields.'))

	def _validate_permissions(self, obj, externalValue):
		"""
		This is our permission checking for PUTS on assignments. Editors
		get full WRITE access, while instructors only get to edit
		assignment policy fields.
		"""
		is_editor = has_permission(nauth.ACT_CONTENT_EDIT, obj, self.request)
		if not is_editor:
			self._validate_instructor_edit(externalValue)

	def _check_object_constraints(self, obj, externalValue):
		self._validate_permissions(obj, externalValue)
		editing_keys = set( externalValue.keys() )
		if 		not IQEditableEvaluation.providedBy(obj) \
			and editing_keys - set( self.legacy_editable_fields ):
			# Cannot edit content backed assessment objects (except
			# for policy keys).
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

	def _get_post_update_source(self, externalValue):
		return externalValue, copy.deepcopy(externalValue)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		originalSource = copy.deepcopy(externalValue)
		externalValue, update_source = self._get_post_update_source( externalValue )
		result = AssessmentPutView.updateContentObject(self,
													   contentObject,
													   externalValue,
													   set_id=set_id,
													   notify=False)
		self.post_update_check(contentObject, update_source)
		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result.model, sources)

		if IQEditableEvaluation.providedBy(contentObject):
			self.handle_evaluation(contentObject, self.course, sources, self.remoteUser)
		# validate changes, subscribers
		if notify:
			self.notify_and_record( contentObject, originalSource )
		return result

@view_config(route_name='objects.generic.traversal',
			 context=IQPoll,
			 request_method='PUT',
			 renderer='rest')
class PollPutView(NewAndLegacyPutView):

	TO_AVAILABLE_MSG = _('Poll will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Poll will become unavailable. Please confirm.')
	OBJ_DEF_CHANGE_MSG = _("Cannot change the poll definition.")

@view_config(route_name='objects.generic.traversal',
			 context=IQSurvey,
			 request_method='PUT',
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
		super( SurveyPutView, self ).post_update_check( contentObject, originalSource )

@view_config(route_name='objects.generic.traversal',
			 context=IQAssignment,
			 request_method='PUT',
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

	def _get_post_update_source(self, externalValue):
		"""
		If our question set just has ntiids, pop from original (in order
		to update without 422ing) and return items for postUpdate.
		"""
		result = dict()
		# Assuming one part per assignment.
		for part in externalValue.get( 'parts' ) or ():
			qset = part.get( 'question_set' )
			if _assignment_part_with_question_set_ntiid_only( part ):
				# Populate a placeholder question set to pass validation.
				# We'll fill in this with the question set corresponding
				# to this ntiid after update.
				result['question_set'] = part.pop( 'question_set' )
				part['question_set'] = {'MimeType': QQuestionSet.mime_type}
			else:
				ntiids_only = _qset_with_ntiids_only( qset ) if qset else None
				if ntiids_only:
					result[ITEMS] = qset.pop( 'questions' )
		return externalValue, result

	def post_update_check(self, contentObject, originalSource):
		if IQEditableEvaluation.providedBy(contentObject):
			if originalSource:  # list of ntiids
				for qset in contentObject.iter_question_sets():  # reset
					qset.questions = indexed_iter()
				self.auto_complete_assignment(contentObject, originalSource)
		# Must complete our set first.
		super( AssignmentPutView, self ).post_update_check( contentObject, originalSource )

	def _transform_to_timed(self, contentObject):
		"""
		Transform from a regular assignment to a timed assignment. This is a
		policy change on the course so we allow these even if we have
		submissions/savepoints.
		"""
		interface.alsoProvides(contentObject, IQTimedAssignment)
		contentObject.mimeType = contentObject.mime_type = TIMED_ASSIGNMENT_MIME_TYPE
		self._re_register(contentObject, IQAssignment, IQTimedAssignment)

	def _transform_to_untimed(self, contentObject):
		"""
		Transform from a timed assignment to a regular assignment. This is a
		policy change on the course so we allow these even if we have
		submissions/savepoints.
		"""
		interface.noLongerProvides(contentObject, IQTimedAssignment)
		contentObject.mimeType = contentObject.mime_type = ASSIGNMENT_MIME_TYPE
		self._re_register(contentObject, IQTimedAssignment, IQAssignment)

	def _update_timed_status(self, externalValue, contentObject):
		"""
		Determine if our object is transitioning to/from a timed assignment.
		Only editors can toggle state on API created assignments.
		"""
		if 		'maximum_time_allowed' in externalValue \
			and IQEditableEvaluation.providedBy(contentObject) \
			and has_permission(nauth.ACT_CONTENT_EDIT, contentObject, self.request):
			if IQDiscussionAssignment.providedBy( contentObject ):
				raise_json_error(self.request,
								 hexc.HTTPUnprocessableEntity,
								 {
									u'message': _("Cannot transform discussion assignment."),
									u'code': 'CannotTransformAssignment',
								 },
								 None)

			# The client passed us something; see if we are going to/from timed assignment.
			max_time_allowed = externalValue.get('maximum_time_allowed')
			if 		max_time_allowed \
				and not IQTimedAssignment.providedBy(contentObject):
				self._transform_to_timed(contentObject)
				# This field is an assignment policy field, we need to set a
				# default value in our object itself that will get overridden
				# by the policy.
				if not getattr(contentObject, 'maximum_time_allowed', None):
					contentObject.maximum_time_allowed = 60
			elif	max_time_allowed is None \
				and IQTimedAssignment.providedBy(contentObject):
				self._transform_to_untimed(contentObject)

	def _validate_timed(self, contentObject, externalValue):
		"""
		Validate that, when making time-allowed changes, we do not currently
		have users taking this assignment.
		"""
		max_time_allowed = externalValue.get('maximum_time_allowed')
		current_time_allowed = None
		if IQTimedAssignment.providedBy(contentObject):
			current_time_allowed = get_max_time_allowed(contentObject, self.course)
		if max_time_allowed != current_time_allowed:
			if IQEditableEvaluation.providedBy(contentObject):
				self._pre_flight_validation(contentObject, externalValue,
											structural_change=True)
			else:
				# We do not want to try to version bump content-backed
				# assignments that might be shared between courses.
				self._validate_structural_edits(contentObject)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		# Must toggle types first (if necessary) before calling super;
		# so everything validates.
		self._validate_timed(contentObject, externalValue)
		self._update_timed_status(externalValue, contentObject)
		result = super(AssignmentPutView, self).updateContentObject(contentObject,
																	externalValue,
																	set_id, notify)
		return result


# get views


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
