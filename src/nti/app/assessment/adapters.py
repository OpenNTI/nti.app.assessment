#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Adapters for application-level events.

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import datetime

from zope import interface
from zope import component
from zope import lifecycleevent
from zope.location import LocationIterator # aka pyramid.location.lineage
from pyramid.traversal import find_interface
from zope.location.interfaces import ILocationInfo
from zope.annotation.interfaces import IAnnotations

from zope.schema.interfaces import ConstraintNotSatisfied
from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import RequiredMissing

from persistent.list import PersistentList

from nti.appserver import interfaces as app_interfaces

from nti.assessment import interfaces as asm_interfaces
from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser

from .history import UsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItem

@component.adapter(asm_interfaces.IQuestionSubmission)
@interface.implementer(app_interfaces.INewObjectTransformer)
def _question_submission_transformer( obj ):
	"Grade it, by adapting the object into an IAssessedQuestion"
	return asm_interfaces.IQAssessedQuestion

@component.adapter(asm_interfaces.IQuestionSetSubmission)
@interface.implementer(app_interfaces.INewObjectTransformer)
def _question_set_submission_transformer( obj ):
	"Grade it, by adapting the object into an IAssessedQuestionSet"
	return asm_interfaces.IQAssessedQuestionSet

from functools import partial
from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse
from pyramid.httpexceptions import HTTPCreated
from pyramid import renderers
from nti.externalization.oids import to_external_oid

@component.adapter(IRequest, asm_interfaces.IQAssignmentSubmission)
@interface.implementer(app_interfaces.INewObjectTransformer)
def _assignment_submission_transformer_factory(request, obj):
	"Begin the grading process by adapting it to an IQAssignmentSubmissionPendingAssessment."
	return partial(_assignment_submission_transformer, request)

@component.adapter(IRequest, asm_interfaces.IQAssignmentSubmission)
@interface.implementer(IExceptionResponse)
def _assignment_submission_transformer(request, obj):
	"""
	Begin the grading process by adapting it to an IQAssignmentSubmissionPendingAssessment.

	Because the submission and pending assessment is not stored on the
	user as contained data, we do not actually returned the transformed
	value. Instead, we take control as documented in our
	interface and raise a Created exception
	"""
	pending = asm_interfaces.IQAssignmentSubmissionPendingAssessment(obj)

	result = request.response = HTTPCreated()
	# TODO: Shouldn't this be the external NTIID? This is what ugd_edit_views does though
	result.location = request.resource_url( obj.creator,
											'Objects',
											to_external_oid( pending ) )
	# TODO: Assuming things about the client and renderer.
	renderers.render_to_response('rest', pending, request)
	raise result

@component.adapter(asm_interfaces.IQAssignmentSubmission)
@interface.implementer(asm_interfaces.IQAssignmentSubmissionPendingAssessment)
def _begin_assessment_for_assignment_submission(submission):
	"""
	Begins the assessment process for an assignment by handling
	what can be done automatically. What cannot be done automatically
	is deferred to the assignment's enclosing course (recall
	that assignments live in exactly one location and are not referenced
	outside the context of their enclosing course).
	"""

	# Get the assignment
	assignment = component.getUtility(asm_interfaces.IQAssignment,
									  name=submission.assignmentId)

	# Submissions to an assignment with zero parts are not allowed;
	# those are reserved for the professor
	if len(assignment.parts) == 0:
		ex = ConstraintNotSatisfied("Cannot submit zero-part assignment")
		ex.field = asm_interfaces.IQAssignment['parts']
		raise ex

	# Check that the submission has something for all parts
	assignment_part_ids = [part.question_set.ntiid for part in assignment.parts]
	submission_part_ids = [part.questionSetId for part in submission.parts]

	if sorted(assignment_part_ids) != sorted(submission_part_ids):
		ex = ConstraintNotSatisfied("Incorrect submission parts")
		ex.field = asm_interfaces.IQAssignmentSubmission['parts']
		raise ex

	# We only need to check that the submission is not too early;
	# if it is late, we still allow it at this level, leaving
	# it to the instructor to handle it
	if assignment.available_for_submission_beginning is not None:
		if datetime.datetime.utcnow() < assignment.available_for_submission_beginning:
			ex = ConstraintNotSatisfied("Submitting too early")
			ex.field = asm_interfaces.IQAssignment['available_for_submission_beginning']
			ex.value = assignment.available_for_submission_beginning
			raise ex

	# Now, try to find the enclosing course for this assignment.
	# If one does not exist, we cannot grade because we have nowhere
	# to dispatch to.
	course = ICourseInstance(assignment, None)
	if course is None:
		raise RequiredMissing("Course cannot be found")

	# TODO: Verify that the assignment belongs to this course;
	# our default adapter implicitly guarantees that but
	# something stronger would be good

	assignment_history = component.getMultiAdapter( (course, submission.creator),
													IUsersCourseAssignmentHistory )
	if submission.assignmentId in assignment_history:
		ex = NotUnique("Assignment already submitted")
		ex.field = asm_interfaces.IQAssignmentSubmission['assignmentId']
		ex.value = submission.assignmentId
		raise ex

	submission.containerId = submission.assignmentId

	# Ok, now for each part that can be auto graded, do so, leaving all the others
	# as-they-are
	new_parts = PersistentList()
	for submission_part in submission.parts:
		assignment_part, = [p for p in assignment.parts if p.question_set.ntiid == submission_part.questionSetId]
		if assignment_part.auto_grade:
			__traceback_info__ = submission_part
			submission_part = asm_interfaces.IQAssessedQuestionSet(submission_part)

		new_parts.append( submission_part )


	pending_assessment = QAssignmentSubmissionPendingAssessment( assignmentId=submission.assignmentId,
																 parts=new_parts )
	pending_assessment.containerId = submission.assignmentId
	lifecycleevent.created(pending_assessment)

	# Now record the submission. This will broadcast created and
	# added events for the HistoryItem and an added event for the pending assessment.
	# The HistoryItem will have
	# the course in its lineage.
	assignment_history.recordSubmission( submission, pending_assessment )

	return pending_assessment

@interface.implementer(ICourseInstance)
@component.adapter(asm_interfaces.IQAssignment)
def _course_from_assignment_lineage(assignment):
	"""
	Given a generic assignment, we look through
	its lineage to find a course instance.

	.. note:: Expect this to change. For legacy-style courses,
	   the parent of the assignment will be a IContentUnit,
	   and eventually an ILegacyCourseConflatedContentPackage
	   which can become the course (However, these may not
	   be within an IRoot, so using ILocationInfo may not be safe;
       in that case, fall back to straightforward lineage)
	"""
	location = ILocationInfo(assignment)
	try:
		parents = location.getParents()
	except TypeError: # Not enough info
		# Return just the parents; the default returns this object
		# too
		parents = LocationIterator(assignment.__parent__)

	course = None
	for parent in parents:
		course = ICourseInstance(parent, None)
		if course is not None:
			break
	return course

from .history import UsersCourseAssignmentHistories

def _histories_for_course(course):
	annotations = IAnnotations(course)
	try:
		KEY = 'AssignmentHistories'
		histories = annotations[KEY]
	except KeyError:
		histories = UsersCourseAssignmentHistories()
		annotations[KEY] = histories
		histories.__name__ = KEY
		histories.__parent__ = course

	return histories

@interface.implementer(IUsersCourseAssignmentHistory)
@component.adapter(ICourseInstance,IUser)
def _history_for_user_in_course(course,user):
	"""
	We use an annotation on the course to store a map
	from username to history object.

	Although our history object can theoretically be used
	across all courses, because assignment IDs are unique, there
	are data locality reasons to keep it on the course: it goes
	away after the course does, and it makes it easy to see
	\"progress\" within a course.
	"""
	histories = _histories_for_course(course)
	try:
		history = histories[user.username]
	except KeyError:
		history = UsersCourseAssignmentHistory()
		history.owner = user
		histories[user.username] = history

	return history

def _histories_for_course_path_adapter(course, request):
	return _histories_for_course(course)

def _histories_for_courseenrollment_path_adapter(enrollment, request):
	return _histories_for_course( ICourseInstance(enrollment) )

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentHistoryItem)
def _course_from_history_item_lineage(item):
	course = find_interface(item, ICourseInstance)
	if course is None:
		__traceback_info__ = item
		raise TypeError("Unable to find course")

	return course

from zope.location.interfaces import LocationError
from nti.dataserver.traversal import ContainerAdapterTraversable
from nti.dataserver.users import User

from .interfaces import IUsersCourseAssignmentHistories

@component.adapter(IUsersCourseAssignmentHistories,IRequest)
class _UsersCourseAssignmentHistoriesTraversable(ContainerAdapterTraversable):
	"""
	During request traversal, we will dummy up an assignment history if
	we need to, if the user exists.

	.. todo:: Only do this when the user is enrolled. We need a cheap
		way to test that first.
	"""

	def traverse( self, key, remaining_path ):
		try:
			return super(_UsersCourseAssignmentHistoriesTraversable,self).traverse(key, remaining_path)
		except LocationError:
			# Ok, is the key an existing user?
			user = User.get_user(key)
			if user is not None:
				return _history_for_user_in_course( self.context.__parent__, user)
			raise

from .interfaces import ICourseAssessmentItemCatalog
from .interfaces import ICourseAssignmentCatalog
from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.assessment.interfaces import IQAssignment


@interface.implementer(ICourseAssessmentItemCatalog)
@component.adapter(ICourseInstance)
class _DefaultCourseAssessmentItemCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assessment_items(self):
		# In theory, the course outline and assessment objects could stretch across multiple content
		# packages. However, in practice, at the moment,
		# it only has one and is an instance of the LegacyCommunityBasedCourseInstance.
		# Because this is simpler to write and test, we directly use that.
		# We will begin to fail when other types of courses are in use,
		# and will start walking through the outline at that time.
		content_package = self.context.legacy_content_package

		result = []
		def _recur(unit):
			items = IQAssessmentItemContainer( unit, () )
			for item in items:
				result.append(item)
			for child in unit.children:
				_recur(child)
		_recur(content_package)

		# On py3.3, can easily 'yield from' nested generators

		return result


@interface.implementer(ICourseAssignmentCatalog)
@component.adapter(ICourseInstance)
class _DefaultCourseAssignmentCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assignments(self):
		return (x for x in ICourseAssessmentItemCatalog(self.context).iter_assessment_items() if IQAssignment.providedBy(x))
