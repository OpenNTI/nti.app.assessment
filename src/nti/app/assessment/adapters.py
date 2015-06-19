#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Adapters for application-level events.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import datetime

from zope import interface
from zope import component
from zope import lifecycleevent

from zope.annotation.interfaces import IAnnotations

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import ConstraintNotSatisfied

from persistent.list import PersistentList

from nti.appserver.interfaces import INewObjectTransformer

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessedQuestion
from nti.assessment.interfaces import IQuestionSubmission
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQuestionSetSubmission
from nti.assessment.interfaces import IQAssignmentDateContext
from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contentlibrary.indexed_data.interfaces import IContainedTypeAdapter

from nti.contenttypes.presentation.interfaces import INTIPollRef
from nti.contenttypes.presentation.interfaces import INTISurveyRef
from nti.contenttypes.presentation.interfaces import INTIAssignmentRef

from nti.dataserver.interfaces import IUser

from nti.traversal.traversal import find_interface

from .history import UsersCourseAssignmentHistory

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistories
from .interfaces import IUsersCourseAssignmentHistoryItem

@component.adapter(IQuestionSubmission)
@interface.implementer(INewObjectTransformer)
def _question_submission_transformer(obj):
	"""
	Grade it, by adapting the object into an IAssessedQuestion
	"""
	return IQAssessedQuestion

@component.adapter(IQuestionSetSubmission)
@interface.implementer(INewObjectTransformer)
def _question_set_submission_transformer(obj):
	"""
	Grade it, by adapting the object into an IAssessedQuestionSet
	"""
	return IQAssessedQuestionSet

from functools import partial

from pyramid import renderers
from pyramid.interfaces import IRequest
from pyramid.httpexceptions import HTTPCreated
from pyramid.interfaces import IExceptionResponse

from nti.externalization.oids import to_external_oid

@component.adapter(IRequest, IQAssignmentSubmission)
@interface.implementer(INewObjectTransformer)
def _assignment_submission_transformer_factory(request, obj):
	"""
	Begin the grading process by adapting it to an IQAssignmentSubmissionPendingAssessment.
	"""
	return partial(_assignment_submission_transformer, request)

@component.adapter(IRequest, IQAssignmentSubmission)
@interface.implementer(IExceptionResponse)
def _assignment_submission_transformer(request, obj):
	"""
	Begin the grading process by adapting it to an IQAssignmentSubmissionPendingAssessment.

	Because the submission and pending assessment is not stored on the
	user as contained data, we do not actually returned the transformed
	value. Instead, we take control as documented in our
	interface and raise a Created exception
	"""
	pending = IQAssignmentSubmissionPendingAssessment(obj)

	result = request.response = HTTPCreated()
	# TODO: Shouldn't this be the external NTIID? This is what ugd_edit_views does though
	result.location = request.resource_url(obj.creator,
											'Objects',
											to_external_oid(pending))
	# TODO: Assuming things about the client and renderer.
	renderers.render_to_response('rest', pending, request)
	raise result

def _check_submission_before(dates, assignment):
	# We only need to check that the submission is not too early;
	# if it is late, we still allow it at this level, leaving
	# it to the instructor to handle it.
	# Allow for the course to handle adjusting the dates
	available_beginning = dates.of(assignment).available_for_submission_beginning
	if available_beginning is not None:
		if datetime.datetime.utcnow() < available_beginning:
			ex = ConstraintNotSatisfied("Submitting too early")
			ex.field = IQAssignment['available_for_submission_beginning']
			ex.value = available_beginning
			raise ex

from .common import get_course_from_assignment

from ._submission import set_submission_lineage

@component.adapter(IQAssignmentSubmission)
@interface.implementer(IQAssignmentSubmissionPendingAssessment)
def _begin_assessment_for_assignment_submission(submission):
	"""
	Begins the assessment process for an assignment by handling
	what can be done automatically. What cannot be done automatically
	is deferred to the assignment's enclosing course (recall
	that assignments live in exactly one location and are not referenced
	outside the context of their enclosing course---actually, this is
	no longer exactly true, but we can still associate a course enrollment).
	"""
	# Get the assignment
	assignment = component.getUtility(IQAssignment, name=submission.assignmentId)

	# Submissions to an assignment with zero parts are not allowed;
	# those are reserved for the professor
	if len(assignment.parts) == 0:
		ex = ConstraintNotSatisfied("Cannot submit zero-part assignment")
		ex.field = IQAssignment['parts']
		raise ex

	# Check that the submission has something for all parts
	assignment_part_ids = [part.question_set.ntiid for part in assignment.parts]
	submission_part_ids = [part.questionSetId for part in submission.parts]

	if sorted(assignment_part_ids) != sorted(submission_part_ids):
		ex = ConstraintNotSatisfied("Incorrect submission parts")
		ex.field = IQAssignmentSubmission['parts']
		raise ex

	course = get_course_from_assignment(assignment, submission.creator)

	_check_submission_before(IQAssignmentDateContext(course), assignment)

	assignment_history = component.getMultiAdapter((course, submission.creator),
													IUsersCourseAssignmentHistory)
	if submission.assignmentId in assignment_history:
		ex = NotUnique("Assignment already submitted")
		ex.field = IQAssignmentSubmission['assignmentId']
		ex.value = submission.assignmentId
		raise ex

	set_submission_lineage(submission)
	submission.containerId = submission.assignmentId

	# Ok, now for each part that can be auto graded, do so, leaving all the others
	# as-they-are
	new_parts = PersistentList()
	for submission_part in submission.parts:
		assignment_part, = [p for p in assignment.parts \
							if p.question_set.ntiid == submission_part.questionSetId]
		if assignment_part.auto_grade:
			__traceback_info__ = submission_part
			submission_part = IQAssessedQuestionSet(submission_part)
		new_parts.append(submission_part)
	pending_assessment = QAssignmentSubmissionPendingAssessment(assignmentId=submission.assignmentId,
																 parts=new_parts)
	pending_assessment.containerId = submission.assignmentId
	lifecycleevent.created(pending_assessment)

	# Now record the submission. This will broadcast created and
	# added events for the HistoryItem and an added event for the pending assessment.
	# The HistoryItem will have
	# the course in its lineage.
	assignment_history.recordSubmission(submission, pending_assessment)
	return pending_assessment

from zope.security.interfaces import IPrincipal

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import IPrincipalEnrollments

@interface.implementer(ICourseInstance)
@component.adapter(IQAssignment, IUser)
def _course_from_assignment_lineage(assignment, user):
	"""
	Given a generic assignment and a user, we
	attempt to associate the assignment with the most
	specific course instance relevant for the user.

	In legacy-style courses, the parent of the assignment will be a
	IContentUnit, and eventually an
	ILegacyCourseConflatedContentPackage which can become the course
	directly. (However, these may not be within an IRoot, so using
	ILocationInfo may not be safe; in that case, fall back to
	straightforward lineage)

	In more sophisticated cases involving sections, the assumption
	that a course instance is one-to-one with a contentpackage
	is broken. In that case, it's better to try to look through
	the things the user is enrolled in and try to match the content
	package to the first course.
	"""

	# Actually, in every case, we want to check enrollment, so
	# we always use that first.

	# However, in old databases, with really legacy courses,
	# we find that the instructors are also enrolled in the courses...
	# and in some places, we had a course that was both old and new, briefly,
	# leading to issues distinguishing which one we want.

	# To handle that case, and to be robust about removing/delisting
	# courses, we begin by checking each entry in the course catalog;
	# the old courses will no longer be present. This also
	# reduces the number of loops we have to make slightly.

	package = find_interface(assignment, IContentPackage, strict=False)
	if package is None:
		return None

	# Nothing. OK, maybe we're an instructor?
	catalog = component.queryUtility(ICourseCatalog)
	if catalog is None:
		return

	prin = IPrincipal(user)
	for entry in catalog.iterCatalogEntries():
		course = ICourseInstance(entry)
		if package in course.ContentPackageBundle.ContentPackages:
			# Ok, found one. Are we enrolled or an instructor?
			if prin in course.instructors:
				return course
			if ICourseEnrollments(course).get_enrollment_for_principal(user) is not None:
				return course

	# Snap. No current course matches. Fall back to the old approach of checking
	# all your enrollments. This could find things not currently in the catalog.
	# TODO: Probably really inefficient
	for enrollments in component.subscribers((user,), IPrincipalEnrollments):
		for enrollment in enrollments.iter_enrollments():
			course = ICourseInstance(enrollment)
			if package in course.ContentPackageBundle.ContentPackages:
				return course
			if ICourseEnrollments(course).get_enrollment_for_principal(user) is not None:
				return course

from .history import UsersCourseAssignmentHistories

@component.adapter(ICourseInstance)
@interface.implementer(IUsersCourseAssignmentHistories)
def _histories_for_course(course, create=True):
	histories = None
	annotations = IAnnotations(course)
	try:
		KEY = 'AssignmentHistories'
		histories = annotations[KEY]
	except KeyError:
		if create:
			histories = UsersCourseAssignmentHistories()
			annotations[KEY] = histories
			histories.__name__ = KEY
			histories.__parent__ = course
	return histories

@interface.implementer(IUsersCourseAssignmentHistory)
@component.adapter(ICourseInstance, IUser)
def _history_for_user_in_course(course, user, create=True):
	"""
	We use an annotation on the course to store a map
	from username to history object.

	Although our history object can theoretically be used
	across all courses, because assignment IDs are unique, there
	are data locality reasons to keep it on the course: it goes
	away after the course does, and it makes it easy to see
	\"progress\" within a course.

	:keyword create: Defaulting to true, if no history already
		exists, one will be created. Set to false to avoid this;
		if many histories do not exist this can save significant
		time.
	"""
	histories = _histories_for_course(course)
	history = None
	try:
		history = histories[user.username]
	except KeyError:
		if create:
			history = UsersCourseAssignmentHistory()
			history.owner = user
			histories[user.username] = history
	return history

def _histories_for_course_path_adapter(course, request):
	return _histories_for_course(course)

def _histories_for_courseenrollment_path_adapter(enrollment, request):
	return _histories_for_course(ICourseInstance(enrollment))

from zope.location.interfaces import LocationError

from nti.dataserver.users import User

from nti.traversal.traversal import ContainerAdapterTraversable

@component.adapter(IUsersCourseAssignmentHistories, IRequest)
class _UsersCourseAssignmentHistoriesTraversable(ContainerAdapterTraversable):
	"""
	During request traversal, we will dummy up an assignment history if
	we need to, if the user exists.

	.. todo:: Only do this when the user is enrolled. We need a cheap
		way to test that first.
	"""

	def traverse(self, key, remaining_path):
		try:
			return super(_UsersCourseAssignmentHistoriesTraversable, self).traverse(key, remaining_path)
		except LocationError:
			# Ok, is the key an existing user?
			user = User.get_user(key)
			if user is not None:
				return _history_for_user_in_course(self.context.__parent__, user)
			raise

from .interfaces import ICourseAssignmentCatalog
from .interfaces import ICourseAssessmentItemCatalog

from .common import get_course_assignments
from .common import get_course_assessment_items

@component.adapter(ICourseInstance)
@interface.implementer(ICourseAssessmentItemCatalog)
class _DefaultCourseAssessmentItemCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assessment_items(self):
		result = get_course_assessment_items(self.context)
		return result

@interface.implementer(ICourseAssignmentCatalog)
@component.adapter(ICourseInstance)
class _DefaultCourseAssignmentCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assignments(self):
		result = get_course_assignments(self.context, sort=False)
		return result

@interface.implementer(ICourseInstance)
def _course_from_context_lineage(context, validate=False):
	course = find_interface(context, ICourseInstance, strict=False)
	if validate and course is None:
		__traceback_info__ = context
		raise component.ComponentLookupError("Unable to find course")
	return course

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentHistoryItem)
def _course_from_history_item_lineage(item):
	return _course_from_context_lineage(item)

