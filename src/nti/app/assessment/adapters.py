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
from functools import partial

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.annotation.interfaces import IAnnotations

from zope.schema.interfaces import NotUnique
from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid import renderers

from pyramid import httpexceptions as hexc

from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse

from zope.location.interfaces import LocationError

from nti.app.assessment.common import set_assessed_lineage
from nti.app.assessment.common import get_course_evaluations
from nti.app.assessment.common import get_evaluation_courses
from nti.app.assessment.common import get_course_assignments
from nti.app.assessment.common import check_submission_version
from nti.app.assessment.common import get_course_from_assignment
from nti.app.assessment.common import get_course_self_assessments
from nti.app.assessment.common import assess_assignment_submission
from nti.app.assessment.common import get_available_for_submission_beginning

from nti.app.assessment.history import UsersCourseAssignmentHistory
from nti.app.assessment.history import UsersCourseAssignmentHistories

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.app.products.courseware.utils import get_course_and_parent

from nti.appserver.context_providers import get_hierarchy_context
from nti.appserver.context_providers import get_joinable_contexts
from nti.appserver.context_providers import get_top_level_contexts
from nti.appserver.context_providers import get_top_level_contexts_for_user

from nti.appserver.interfaces import INewObjectTransformer
from nti.appserver.interfaces import IJoinableContextProvider
from nti.appserver.interfaces import IHierarchicalContextProvider
from nti.appserver.interfaces import ITopLevelContainerContextProvider
from nti.appserver.interfaces import ITrustedTopLevelContainerContextProvider

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQSubmittable
from nti.assessment.interfaces import IQAssessedQuestion
from nti.assessment.interfaces import IQuestionSubmission
from nti.assessment.interfaces import IQAssessedQuestionSet
from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQuestionSetSubmission
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import ICourseAssessmentItemCatalog
from nti.contenttypes.courses.interfaces import ICourseSelfAssessmentItemCatalog

from nti.contenttypes.courses.utils import is_enrolled
from nti.contenttypes.courses.utils import get_enrollments
from nti.contenttypes.courses.utils import get_courses_for_packages
from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.externalization.oids import to_external_oid

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable

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

	result = request.response = hexc.HTTPCreated()
	# TODO: Shouldn't this be the external NTIID? This is what ugd_edit_views does though
	result.location = request.resource_url(obj.creator,
										   'Objects',
										   to_external_oid(pending))
	# TODO: Assuming things about the client and renderer.
	try:
		renderers.render_to_response('rest', pending, request, response=result)
	except TypeError:
		# Pyramid 1.5?
		renderers.render_to_response('rest', pending, request)
	raise result

def _is_instructor_or_editor(course, user):
	return 	   	(user is not None and course is not None) \
			and (is_course_instructor_or_editor(course, user) \
				 or has_permission(ACT_CONTENT_EDIT, course))

def _check_submission_before(submission, course, assignment):
	# We only need to check that the submission is not too early;
	# If it is late, we still allow it at this level, leaving
	# it to the instructor to handle it.
	# Allow for the course to handle adjusting the dates
	if _is_instructor_or_editor(course, submission.creator):
		return
	available_beginning = get_available_for_submission_beginning(assignment, course)
	if available_beginning is not None:
		if datetime.datetime.utcnow() < available_beginning:
			ex = ConstraintNotSatisfied("Submitting too early")
			ex.field = IQSubmittable['available_for_submission_beginning']
			ex.value = available_beginning
			raise ex

def _validate_submission(submission, course, assignment):
	_check_submission_before(submission, course, assignment)
	check_submission_version(submission, assignment)

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

	course = get_course_from_assignment(assignment, submission.creator, exc=True)

	_validate_submission(submission, course, assignment)

	assignment_history = component.getMultiAdapter((course, submission.creator),
													IUsersCourseAssignmentHistory)
	if submission.assignmentId in assignment_history:
		ex = NotUnique("Assignment already submitted")
		ex.field = IQAssignmentSubmission['assignmentId']
		ex.value = submission.assignmentId
		raise ex

	set_assessed_lineage(submission)
	submission.containerId = submission.assignmentId

	pending_assessment = assess_assignment_submission(course, assignment, submission)
	set_assessed_lineage(pending_assessment)
	lifecycleevent.created(pending_assessment)

	version = assignment.version
	if version is not None:  # record version
		pending_assessment.version = submission.version = version

	# Now record the submission. This will broadcast created and
	# added events for the HistoryItem and an added event for the pending assessment.
	# The HistoryItem will have
	# the course in its lineage.
	assignment_history.recordSubmission(submission, pending_assessment)
	return pending_assessment

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

@component.adapter(ICourseInstance)
@interface.implementer(ICourseAssessmentItemCatalog)
class _DefaultCourseAssessmentItemCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assessment_items(self):
		result = get_course_evaluations(self.context)
		return result

@component.adapter(ICourseInstance)
@interface.implementer(ICourseSelfAssessmentItemCatalog)
class _DefaultCourseSelfAssessmentItemCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assessment_items(self, exclude_editable=True):
		result = get_course_self_assessments(self.context,
											 exclude_editable=exclude_editable)
		return result

@component.adapter(ICourseInstance)
@interface.implementer(ICourseAssignmentCatalog)
class _DefaultCourseAssignmentCatalog(object):

	def __init__(self, context):
		self.context = context

	def iter_assignments(self, course_lineage=False):
		if course_lineage:
			courses = get_course_and_parent(self.context)
		else:
			courses = (self.context,)

		# We're gathering parent courses; make sure we exclude duplicates.
		if len(courses) > 1:
			result = []
			seen = set()
			for course in courses:
				course_assignments = get_course_assignments(course, sort=False)
				for assignment in course_assignments or ():
					if assignment.ntiid not in seen:
						seen.add(assignment.ntiid)
						result.append(assignment)
		else:
			result = get_course_assignments(courses[0], sort=False)
		return result

@interface.implementer(ICourseInstance)
def course_from_context_lineage(context, validate=False):
	course = find_interface(context, ICourseInstance, strict=False)
	if validate and course is None:
		__traceback_info__ = context
		raise component.ComponentLookupError("Unable to find course")
	return course
_course_from_context_lineage = course_from_context_lineage  # BWC

@interface.implementer(ICourseInstance)
@component.adapter(IUsersCourseAssignmentHistoryItem)
def course_from_history_item_lineage(item):
	return course_from_context_lineage(item)
_course_from_history_item_lineage = course_from_history_item_lineage  # BWC

def _legacy_course_from_submittable_lineage(assesment, user):
	"""
	Given a generic assesment and a user, we
	attempt to associate the assesment with the most
	specific course instance relevant for the user.

	In legacy-style courses, the parent of the assesment will be a
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

	package = find_interface(assesment, IContentPackage, strict=False)
	if package is None:
		return None

	# Nothing. OK, maybe we're an instructor?
	catalog = component.queryUtility(ICourseCatalog)
	if catalog is None:
		return

	for course in get_courses_for_packages(packages=package.ntiid):
		if 		is_course_instructor_or_editor(course, user) \
			or	is_enrolled(course, user):
			return course

	# Snap. No current course matches. Fall back to the old approach of checking
	# all your enrollments. This could find things not currently in the catalog.
	for enrollment in get_enrollments(user):
		course = ICourseInstance(enrollment, None)
		if 		course is not None \
			and package in course.ContentPackageBundle.ContentPackages:
			return course
	return None

@interface.implementer(ICourseInstance)
@component.adapter(IQSubmittable, IUser)
def course_from_submittable_lineage(assesment, user):
	courses = get_evaluation_courses(assesment)
	for course in courses or ():
		if 		is_course_instructor_or_editor(course, user) \
			or	is_enrolled(course, user):
			return course
	return _legacy_course_from_submittable_lineage(assesment, user)

def _get_hierarchy_context_for_context(obj, top_level_context):
	results = component.queryMultiAdapter((top_level_context, obj),
										  IHierarchicalContextProvider)
	return results or (top_level_context,)

def _get_assessment_container(obj):
	return 		find_interface(obj, ICourseInstance, strict=False) \
			or	find_interface(obj, IContentUnit, strict=False)

@interface.implementer(ITopLevelContainerContextProvider)
@component.adapter(IQInquiry)
@component.adapter(IQAssessment)
def _courses_from_obj(obj):
	results = ()
	container = _get_assessment_container(obj)
	if container is not None:
		results = get_top_level_contexts(container)
	return results

@interface.implementer(ITopLevelContainerContextProvider)
@component.adapter(IQInquiry, IUser)
@component.adapter(IQAssessment, IUser)
def _courses_from_obj_and_user(obj, user):
	results = ()
	container = _get_assessment_container(obj)
	if container is not None:
		results = get_top_level_contexts_for_user(container, user)
	return results

@interface.implementer(IHierarchicalContextProvider)
@component.adapter(IQInquiry, IUser)
@component.adapter(IQAssessment, IUser)
def _hierarchy_from_obj_and_user(obj, user):
	results = ()
	container = _get_assessment_container(obj)
	if container is not None:
		if IContentUnit.providedBy(container):
			results = get_hierarchy_context(container, user)
		else:
			results = _get_hierarchy_context_for_context(obj, container)
	return results

@interface.implementer(IJoinableContextProvider)
@component.adapter(IQInquiry)
@component.adapter(IQAssessment)
def _joinable_courses_from_obj(obj):
	container = _get_assessment_container(obj)
	return get_joinable_contexts(container)

@interface.implementer(ITrustedTopLevelContainerContextProvider)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
def _trusted_context_from_feedback(obj):
	results = ()
	course = _course_from_context_lineage(obj)
	if course is not None:
		catalog_entry = ICourseCatalogEntry(course, None)
		results = (catalog_entry,) if catalog_entry is not None else ()
	return results
