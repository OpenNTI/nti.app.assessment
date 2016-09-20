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
from collections import Mapping

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.event import notify as event_notify

from zope.i18n import translate

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import MessageFactory as _

from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_COPY_EVALUATION
from nti.app.assessment import VIEW_RESET_EVALUATION
from nti.app.assessment import VIEW_REGRADE_EVALUATION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS
from nti.app.assessment import VIEW_USER_RESET_EVALUATION

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import regrade_evaluation
from nti.app.assessment.common import validate_auto_grade
from nti.app.assessment.common import make_evaluation_ntiid
from nti.app.assessment.common import get_auto_grade_policy
from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import has_inquiry_submissions
from nti.app.assessment.common import delete_evaluation_metadata
from nti.app.assessment.common import delete_inquiry_submissions
from nti.app.assessment.common import get_evaluation_containment
from nti.app.assessment.common import get_course_from_evaluation
from nti.app.assessment.common import pre_validate_question_change
from nti.app.assessment.common import delete_evaluation_savepoints
from nti.app.assessment.common import delete_evaluation_submissions
from nti.app.assessment.common import is_assignment_non_public_only
from nti.app.assessment.common import get_assignments_for_evaluation_object

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import validate_structural_edits
from nti.app.assessment.evaluations.utils import import_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations
from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import RegradeQuestionEvent
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint

from nti.app.assessment.utils import get_course_from_request

from nti.app.assessment.views.view_mixins import AssessmentPutView
from nti.app.assessment.views.view_mixins import StructuralValidationMixin

from nti.app.assessment.views.view_mixins import get_courses_from_assesment

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.internalization import read_body_as_external_object

from nti.app.externalization.view_mixins import BatchingUtilsMixin
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.contentfile import validate_sources

from nti.app.products.courseware.views.view_mixins import IndexedRequestMixin
from nti.app.products.courseware.views.view_mixins import DeleteChildViewMixin
from nti.app.products.courseware.views.view_mixins import AbstractChildMoveView

from nti.app.publishing import VIEW_PUBLISH
from nti.app.publishing import VIEW_UNPUBLISH

from nti.app.publishing.views import CalendarPublishView
from nti.app.publishing.views import CalendarUnpublishView

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
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQEvaluationItemContainer

from nti.assessment.interfaces import QAssessmentPoliciesModified
from nti.assessment.interfaces import QuestionInsertedInContainerEvent
from nti.assessment.interfaces import QuestionRemovedFromContainerEvent

from nti.assessment.interfaces import QuestionMovedEvent

from nti.assessment.question import QQuestionSet

from nti.assessment.randomized.interfaces import IQuestionBank

from nti.assessment.randomized.question import QQuestionBank

from nti.common.maps import CaseInsensitiveDict

from nti.common.string import is_true

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_course_instructor

from nti.coremetadata.interfaces import ICalendarPublishable

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified
from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.externalization.proxy import removeAllProxies

from nti.links.links import Link

from nti.mimetype.externalization import decorateMimeType

from nti.recorder.record import copy_transaction_history

from nti.property.property import Lazy

from nti.site.hostpolicy import get_host_site

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

OID = StandardExternalFields.OID
ITEMS = StandardExternalFields.ITEMS
LINKS = StandardExternalFields.LINKS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
MIMETYPE = StandardExternalFields.MIMETYPE
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

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
		accept = params.get('accept') or params.get('mimeTypes') or u''
		accept = accept.split(',') if accept else ()
		if accept and '*/*' not in accept:
			accept = {e.strip().lower() for e in accept if e}
			accept.discard(u'')
		else:
			accept = ()
		return accept

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
		result[ITEM_COUNT] = len(result[ITEMS])
		return result

class EvaluationMixin(StructuralValidationMixin):

	@Lazy
	def _extra(self):
		return str(uuid.uuid4()).split('-')[0].upper()

	def get_ntiid(self, context):
		if isinstance(context, six.string_types):
			result = context
		else:
			result = getattr(context, 'ntiid', None)
		return result

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
		unregisterUtility(registry, provided=old_iface, name=ntiid)
		# Make sure we re-index.
		self._index(context)

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
			theObject = self.store_evaluation(theObject, course, user,
											  check_solutions)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		[p.ntiid for p in theObject.parts or ()] # set auto part NTIIDs
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
		[p.ntiid for p in theObject.parts or ()] # set auto part NTIIDs
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
			[p.ntiid for p in theObject.parts or ()] # set auto part NTIIDs
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

	def _get_required_question(self, item):
		"""
		Fetch and validate we are given a question object or the ntiid
		of an existing question object.
		"""
		question = self.get_registered_evaluation(item, self.course)
		if not IQuestion.providedBy(question):
			msg = translate(_("Question ${ntiid} does not exist.",
							mapping={'ntiid': item}))
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': msg,
								u'code': 'QuestionDoesNotExist',
							 },
							 None)
		return question

	def _get_required_question_set(self, item):
		"""
		Fetch and validate we are given a question_set object or the ntiid
		of an existing question_set object.
		"""
		question_set = self.get_registered_evaluation(item, self.course)
		if not IQuestionSet.providedBy(question_set):
			msg = translate(_("QuestionSet ${ntiid} does not exist.",
							mapping={'ntiid': item}))
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': msg,
								u'code': 'QuestionSetDoesNotExist',
							 },
							 None)
		return question_set

	def auto_complete_questionset(self, context, externalValue):
		questions = indexed_iter() if not context.questions else context.questions
		items = externalValue.get(ITEMS)
		for item in items or ():
			question = self._get_required_question( item )
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
									u'code': 'QuestionDoesNotExist',
								 },
								 None)
			else:
				questions.append(poll)
		context.questions = questions

	def _default_assignment_public_status(self, context):
		"""
		For the given assignment, set our default public status based
		on whether or not all courses contained by this assignment
		are non-public.
		"""
		is_non_public = is_assignment_non_public_only( context, self.course )
		context.is_non_public = is_non_public

	def auto_complete_assignment(self, context, externalValue):
		# Clients are expected to create parts/qsets as needed.
		parts = indexed_iter() if not context.parts else context.parts
		for part in parts:
			# Assuming one part.
			qset = externalValue.get( 'question_set' )
			if qset:
				part.question_set = self._get_required_question_set( qset )
			if part.question_set is not None:
				self.auto_complete_questionset(part.question_set, externalValue)
		context.parts = parts
		self._default_assignment_public_status( context )

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

	def _validate(self, params):
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

	def __call__(self):
		self._pre_flight_validation( self.context, structural_change=True )
		params = CaseInsensitiveDict(self.request.params)
		index = self._get_index()
		question = self._get_new_question()
		self.context.insert(index, question)
		event_notify(QuestionInsertedInContainerEvent(self.context, question, index))
		logger.info('Inserted new question (%s)', question.ntiid)
		# validate changes
		self._validate( params )
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
		evaluations = ICourseEvaluations( course )
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

	@property
	def legacy_editable_fields(self):
		# XXX: We allow toggling public status? This is the only
		# change that may lock the assignment from syncing.
		return ('is_non_public',) + self.policy_keys

	def _check_object_constraints(self, obj, externalValue):
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

	def _transform_to_timed(self, contentObject):
		"""
		Transform from a regular assignment to a timed assignment.
		"""
		self._pre_flight_validation(self.context, structural_change=True)
		interface.alsoProvides(contentObject, IQTimedAssignment)
		contentObject.mimeType = contentObject.mime_type = TIMED_ASSIGNMENT_MIME_TYPE
		self._re_register(contentObject, IQAssignment, IQTimedAssignment)

	def _transform_to_untimed(self, contentObject):
		"""
		Transform from a timed assignment to a regular assignment.
		"""
		self._pre_flight_validation(self.context, structural_change=True)
		interface.noLongerProvides(contentObject, IQTimedAssignment)
		contentObject.mimeType = contentObject.mime_type = ASSIGNMENT_MIME_TYPE
		self._re_register(contentObject, IQTimedAssignment, IQAssignment)

	def _update_timed_status(self, externalValue, contentObject):
		"""
		Determine if our object is transitioning to/from a timed assignment.
		"""
		if 'maximum_time_allowed' in externalValue:
			# The client passed us something; see if we are going to/from timed assignment.
			max_time_allowed = externalValue.get('maximum_time_allowed')
			if 		max_time_allowed \
				and not IQTimedAssignment.providedBy(contentObject):
				self._transform_to_timed(contentObject)
			elif	max_time_allowed is None \
				and IQTimedAssignment.providedBy(contentObject):
				self._transform_to_untimed(contentObject)
			elif	max_time_allowed is not None \
				and IQTimedAssignment.providedBy(contentObject) \
				and contentObject.maximum_time_allowed is not None \
				and max_time_allowed != contentObject.maximum_time_allowed:
				# Changing times; validate structurally.
				self._pre_flight_validation(self.context, structural_change=True)

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		# Must toggle types first (if necessary) before calling super; so
		# everything validates.
		self._update_timed_status( externalValue, contentObject )
		result = super(AssignmentPutView, self).updateContentObject(contentObject,
																	externalValue,
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

	def readInput(self, value=None):
		if self.request.body:
			result = CaseInsensitiveDict(read_body_as_external_object(self.request))
		else:
			result = CaseInsensitiveDict(self.request.params)
		return result

	def _check_editable(self, theObject):
		if not IQEditableEvaluation.providedBy(theObject):
			raise hexc.HTTPForbidden(_("Cannot delete legacy object."))

	def _check_containment(self, theObject):
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

	def _check_internal(self, theObject):
		self._check_editable(theObject)
		self._pre_flight_validation(self.context, structural_change=True)
		self._check_containment(theObject)

	def _do_delete_object(self, theObject):
		self._check_internal(theObject)
		delete_evaluation(theObject)
		return theObject

@view_config(route_name="objects.generic.traversal",
			 context=IQuestionSet,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class QuestionSetDeleteView(EvaluationDeleteView):

	def _check_containment(self, theObject):
		containment = get_evaluation_containment(theObject.ntiid)
		if containment:
			values = self.readInput()
			force = is_true(values.get('force'))
			if not force:
				links = (
					Link(self.request.path, rel='confirm',
						 params={'force':True}, method='DELETE'),
				)
				raise_json_error(
						self.request,
						hexc.HTTPConflict,
						{
							u'message': _('This question set is being referenced by other assignments.'),
							u'code': 'QuestionSetIsReferenced',
							LINKS: to_external_object(links)
						},
						None)

@view_config(context=IQPoll)
@view_config(context=IQSurvey)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='DELETE',
			   permission=nauth.ACT_DELETE)
class SubmittableDeleteView(EvaluationDeleteView, ModeledContentUploadRequestUtilsMixin):

	def _can_delete_contained_data(self, theObject):
		return 		is_course_instructor(self.course, self.remoteUser) \
			   or	has_permission(nauth.ACT_NTI_ADMIN, theObject, self.request)

	def _has_submissions(self, theObject):
		if IQInquiry.providedBy(theObject):
			result = has_inquiry_submissions(theObject, self.course)
		else:
			courses = get_courses(self.course)
			result = has_submissions(theObject, courses)
		return result

	def _delete_contained_data(self, theObject):
		if IQInquiry.providedBy(theObject):
			delete_inquiry_submissions(theObject, self.course)
		else:
			delete_evaluation_metadata(theObject, self.course)
			delete_evaluation_savepoints(theObject, self.course)
			delete_evaluation_submissions(theObject, self.course)

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
						 params={'force':True}, method='DELETE'),
				)
				raise_json_error(
						self.request,
						hexc.HTTPConflict,
						{
							u'message': _('There are submissions for this evaluation object.'),
							u'code': 'EvaluationHasSubmissions',
							LINKS: to_external_object(links)
						},
						None)
		self._delete_contained_data(theObject)
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
		self._pre_flight_validation( self.context, structural_change=True)

# Reset views

class EvaluationResetMixin(ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		if self.request.body:
			result = CaseInsensitiveDict(read_body_as_external_object(self.request))
		else:
			result = CaseInsensitiveDict(self.request.params)
		return result

	@Lazy
	def course(self):
		if IQEditableEvaluation.providedBy(self.context):
			result = find_interface(self.context, ICourseInstance, strict=False)
		else:
			result = get_course_from_request(self.request)
			if result is None:
				result = get_course_from_evaluation(self.context, self.remoteUser)
		return result

	def _can_delete_contained_data(self, theObject):
		return is_course_instructor(self.course, self.remoteUser)

@view_config(context=IQPoll)
@view_config(context=IQSurvey)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='POST',
			   name=VIEW_RESET_EVALUATION,
			   permission=nauth.ACT_UPDATE)
class EvaluationResetView(AbstractAuthenticatedView,
						  EvaluationResetMixin):

	def _has_submissions(self, theObject):
		if IQInquiry.providedBy(theObject):
			result = has_inquiry_submissions(theObject, self.course)
		else:
			courses = get_courses(self.course)
			result = 	has_submissions(theObject, courses) \
					or  has_savepoints( theObject, courses )
		return result

	def _delete_contained_data(self, theObject):
		if IQInquiry.providedBy(theObject):
			delete_inquiry_submissions(theObject, self.course)
		else:
			delete_evaluation_metadata(theObject, self.course)
			delete_evaluation_savepoints(theObject, self.course)
			delete_evaluation_submissions(theObject, self.course)

	def __call__(self):
		if not self._can_delete_contained_data(self.context):
			raise_json_error(self.request,
							 hexc.HTTPForbidden,
							 {
								u'message': _("Cannot reset evaluation object."),
								u'code': 'CannotResetEvaluation',
							 },
							 None)
		elif self._has_submissions(self.context):
			self._delete_contained_data(self.context)
		self.context.update_version()
		return self.context

@view_config(context=IQPoll)
@view_config(context=IQSurvey)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   name=VIEW_USER_RESET_EVALUATION,
			   permission=nauth.ACT_UPDATE)
class UserEvaluationResetView(AbstractAuthenticatedView,
							  EvaluationResetMixin):

	def _delete_contained_data(self, course, theObject, usernames):
		result = set()
		ntiid = theObject.ntiid
		if IQInquiry.providedBy(theObject):
			container_interfaces = (IUsersCourseInquiry,)
		else:
			container_interfaces = (IUsersCourseAssignmentHistory,
									IUsersCourseAssignmentMetadata,
									IUsersCourseAssignmentSavepoint)

		for username in usernames or ():
			user = User.get_user(username)
			if not IUser.providedBy(user):
				continue
			for provided in container_interfaces:
				container = component.queryMultiAdapter((course, user), provided)
				if container and ntiid in container:
					del container[ntiid]
					result.add(username)

		return sorted(result)

	def __call__(self):
		values = self.readInput()
		if not self._can_delete_contained_data(self.context):
			raise_json_error(self.request,
							 hexc.HTTPForbidden,
							 {
								u'message': _("Cannot reset evaluation object."),
								u'code': 'CannotResetEvaluation',
							 },
							 None)

		usernames = 	values.get('user') \
					or	values.get('users') \
					or	values.get('username') \
					or	values.get('usernames')
		if isinstance(usernames, six.string_types):
			usernames = usernames.split()
		if not usernames:
			raise_json_error(self.request,
							 hexc.HTTPUnprocessableEntity,
							 {
								u'message': _("Must specify a username."),
								u'code': 'MustSpecifyUsername',
							 },
							 None)

		items = self._delete_contained_data(self.course, self.context, usernames)
		result = LocatedExternalDict()
		result[ITEMS] = items
		result[TOTAL] = result[ITEM_COUNT] = len(items)
		return result

# Publish views

def publish_context(context, start=None, end=None, site_name=None):
	# publish
	if not context.is_published():
		if ICalendarPublishable.providedBy(context):
			context.publish(start=start, end=end)
		else:
			context.publish()
	# register utility
	register_context(context, site_name)
	# process 'children'
	if IQEvaluationItemContainer.providedBy(context):
		for item in context.Items or ():
			publish_context(item, start, end, site_name)
	elif IQAssignment.providedBy(context):
		for item in context.iter_question_sets():
			publish_context(item, start, end, site_name)

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
 			   name=VIEW_PUBLISH,
			   permission=nauth.ACT_UPDATE,
			   request_method='POST')
class EvaluationPublishView(CalendarPublishView):

	def _do_provide(self, context):
		if IQEditableEvaluation.providedBy(context):
			start, end = self._get_dates()
			publish_context(context, start, end)

# Unublish views

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
 			   name=VIEW_UNPUBLISH,
			   permission=nauth.ACT_UPDATE,
			   request_method='POST')
class EvaluationUnpublishView(CalendarUnpublishView):

	def _do_provide(self, context):
		if IQEditableEvaluation.providedBy(context):
			course = find_interface(context, ICourseInstance, strict=True)
			courses = get_courses( course )
			for course in courses:
				# Not allowed to unpublish if we have submissions/savepoints.
				validate_structural_edits( context, course )
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
			and not has_permission(nauth.ACT_CONTENT_EDIT, result, self.request):
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

@view_config(context=IQuestion)
@view_config(context=IQAssignment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='POST',
			   name=VIEW_REGRADE_EVALUATION,
			   permission=nauth.ACT_READ)
class RegradeEvaluationView(AbstractAuthenticatedView):

	@property
	def _admin_user(self):
		return self.remoteUser.username.endswith('@nextthought.com')

	def _get_instructor(self):
		params = CaseInsensitiveDict(self.request.params)
		username = params.get( 'user' ) \
				or params.get( 'username' ) \
				or params.get( 'instructor' )
		result = User.get_user( username )
		if result is None:
			raise_json_error(self.request,
							 hexc.HTTPForbidden,
							 {
								u'message': _("No instructor found."),
								u'code': 'CannotFindInstructor',
							 },
							 None)
		return result

	def _get_course_from_evaluation(self, theObject):
		result = get_course_from_request(self.request)
		if result is None:
			result = get_course_from_evaluation(evaluation=theObject,
										  		user=self.remoteUser)
		return result

	def _can_regrade_evaluation(self, theObject, user):
		course = self._get_course_from_evaluation(theObject)
		if course is None:
			raise_json_error(self.request,
							 hexc.HTTPForbidden,
							 {
								u'message': _("Cannot find evaluation course."),
								u'code': 'CannotFindEvaluationCourse',
							 },
							 None)
		if not is_course_instructor(course, user):
			raise_json_error(self.request,
							 hexc.HTTPForbidden,
							 {
								u'message': _("Cannot regrade evaluation."),
								u'code': 'CannotRegradeEvaluation',
							 },
							 None)
		return course

	def __call__(self):
		user = self.remoteUser
		if self._admin_user:
			# We allow admin users to regrade as instructors.
			user = self._get_instructor()
		course = self._can_regrade_evaluation(self.context, user)
		logger.info( '%s regrading %s (%s)',
					 user.username, self.context.ntiid, self.remoteUser.username)
		# The grade object itself actually randomly picks an
		# instructor as the creator.
		regrade_evaluation(self.context, course)
		return self.context
