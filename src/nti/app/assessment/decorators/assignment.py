#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import Mapping
from collections import namedtuple

from datetime import datetime

from zope import component
from zope import interface

from zope.location.interfaces import ILocation

from nti.app.assessment import VIEW_MOVE_PART
from nti.app.assessment import VIEW_RANDOMIZE
from nti.app.assessment import VIEW_UNRANDOMIZE
from nti.app.assessment import VIEW_INSERT_PART
from nti.app.assessment import VIEW_REMOVE_PART
from nti.app.assessment import VIEW_ASSESSMENT_MOVE
from nti.app.assessment import VIEW_RANDOMIZE_PARTS
from nti.app.assessment import VIEW_MOVE_PART_OPTION
from nti.app.assessment import VIEW_UNRANDOMIZE_PARTS
from nti.app.assessment import VIEW_INSERT_PART_OPTION
from nti.app.assessment import VIEW_REMOVE_PART_OPTION
from nti.app.assessment import VIEW_QUESTION_SET_CONTENTS
from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import get_max_time_allowed
from nti.app.assessment.common import is_part_auto_gradable
from nti.app.assessment.common import get_auto_grade_policy
from nti.app.assessment.common import get_assessment_metadata_item
from nti.app.assessment.common import get_available_for_submission_ending
from nti.app.assessment.common import get_assignments_for_evaluation_object
from nti.app.assessment.common import get_available_for_submission_beginning
from nti.app.assessment.common import get_available_assignments_for_evaluation_object

from nti.app.assessment.decorators import _root_url
from nti.app.assessment.decorators import _get_course_from_evaluation
from nti.app.assessment.decorators import AbstractAssessmentDecoratorPredicate

from nti.app.assessment.interfaces import ACT_VIEW_SOLUTIONS

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.app.assessment.utils import assignment_download_precondition

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet
from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.common.property import Lazy

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses import get_course_vendor_info

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import is_course_instructor
from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalObjectDecorator
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.externalization.singleton import SingletonDecorator

from nti.links.links import Link

from nti.traversal.traversal import find_interface

OID = StandardExternalFields.OID
LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _AssignmentsByOutlineNodeDecorator(AbstractAssessmentDecoratorPredicate):
	"""
	For things that have a assignments, add this as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor. Those registrations are more general,
	# though, because we try to always go through a course, if possible
	# (because of issues resolving really old enrollment records), although
	# the enrollment record is a better place to go because it has the username
	# in the path

	def show_assignments_by_outline_link(self, course):
		"""
		Returns a true value if the course should show the links [Non] assignments
		by outline node links
		"""
		# TODO: We will remove when a preference course/user? policy is in place.
		vendor_info = get_course_vendor_info(course, False) or {}
		try:
			result = vendor_info['NTI']['show_assignments_by_outline']
		except (TypeError, KeyError):
			result = True
		return result

	def _link_with_rel(self, course, rel):
		link = Link(course,
					rel=rel,
					elements=(rel,),
					# We'd get the wrong type/ntiid values if we
					# didn't ignore them.
					ignore_properties_of_target=True)
		return link

	def _do_decorate_external(self, context, result_map):
		course = ICourseInstance(context, context)

		links = result_map.setdefault(LINKS, [])
		links.append(self._link_with_rel(course, 'NonAssignmentAssessmentItemsByOutlineNode'))

		if self.show_assignments_by_outline_link(course):
			links.append(self._link_with_rel(course, 'AssignmentsByOutlineNode'))

class _AssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an instructor fetches an assignment that contains a file part
	somewhere, provide access to the link do download it.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return assignment_download_precondition(context, self.request, self.remoteUser)  # XXX Hack

	def _do_decorate_external(self, context, result):
		# TODO: It would be better to have the course context in our link,
		# but for now, we'll just have a course param.
		course = _get_course_from_evaluation(context, self.remoteUser, request=self.request)
		catalog_entry = ICourseCatalogEntry(course, None)
		if catalog_entry is not None:
			parameters = { 'course' : catalog_entry.ntiid }
		else:
			parameters = None
		links = result.setdefault(LINKS, [])
		links.append(Link(context,
						  rel='ExportFiles',
						  elements=('BulkFilePartDownload',),
						  params=parameters))

class _AssignmentOverridesDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an assignment is externalized, check for overrides.
	"""

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result

	def _do_decorate_external(self, assignment, result):
		course = _get_course_from_evaluation(assignment,
											 self.remoteUser,
											 self._catalog,
											 request=self.request)
		if course is None:
			return

		# Do not override dates if locked.
		start_date = get_available_for_submission_beginning(assignment, course)
		end_date = get_available_for_submission_ending(assignment, course)
		result['available_for_submission_beginning'] = to_external_object(start_date)
		result['available_for_submission_ending'] = to_external_object(end_date)

		if IQTimedAssignment.providedBy(assignment):
			max_time_allowed = get_max_time_allowed(assignment, course)
			result['IsTimedAssignment'] = True
			result['MaximumTimeAllowed'] = result['maximum_time_allowed' ] = max_time_allowed
		else:
			result['IsTimedAssignment'] = False

		# auto_grade/total_points
		auto_grade = get_auto_grade_policy( assignment, course )
		if auto_grade:
			disabled = auto_grade.get( 'disable' )
			result['auto_grade'] = not disabled if disabled is not None else None
			result['total_points'] = auto_grade.get( 'total_points' )

class _TimedAssignmentPartStripperDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, context, result):
		course = _get_course_from_evaluation(context,
											 user=self.remoteUser,
											 request=self.request)

		if 	   course is None \
			or is_course_instructor( course, self.remoteUser ) \
			or has_permission(ACT_CONTENT_EDIT, course, self.request):
			return
		item = get_assessment_metadata_item(course, self.remoteUser, context.ntiid)
		if item is None or not item.StartTime:
			result['parts'] = None

class _AssignmentMetadataDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, context, result):
		course = _get_course_from_evaluation(context,
											 user=self.remoteUser,
											 request=self.request)
		if 	   course is None \
			or is_course_instructor( course, self.remoteUser ) \
			or has_permission(ACT_CONTENT_EDIT, course, self.request):
			return
		item = get_assessment_metadata_item(course, self.remoteUser, context.ntiid)
		if item is not None:
			metadata = {'Duration': item.Duration, 'StartTime': item.StartTime}
			result['Metadata'] = metadata

class _AssignmentQuestionContentRootURLAdder(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an assignment question is externalized, add the bucket root
	"""

	def _do_decorate_external(self, context, result):
		ntiid = getattr(context, 'ContentUnitNTIID', None)
		if not ntiid:
			content_unit = find_interface(context, IContentUnit, strict=False)
			if content_unit is not None:
				ntiid = content_unit.ntiid
			else:
				assignment = find_interface(context, IQAssignment, strict=False)
				ntiid = getattr(assignment, 'ContentUnitNTIID', None)

		bucket_root = _root_url(ntiid) if ntiid else None
		if bucket_root:
			result['ContentRoot'] = bucket_root

class _AssignmentBeforeDueDateSolutionStripper(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When anyone besides the instructor or an editor requests an assignment
	that has a due date, and we are before the due date, do not release
	the answers.

	.. note:: This is currently incomplete. We are also sending these
		question set items back 'standalone'. Depending on the UI, we
		may need to strip them there too.
	"""

	@classmethod
	def needs_stripped(cls, context, request, remoteUser):
		if context is not None:
			course = _get_course_from_evaluation(context, remoteUser, request=request)
		else:
			course = None

		if course is None:
			logger.warn("Could not adapt %s to course", context)
			return False

		if 	   has_permission(ACT_VIEW_SOLUTIONS, course, request) \
			or has_permission(ACT_CONTENT_EDIT, course, request):
			# The instructor or an editor, nothing to do
			return False

		due_date = get_available_for_submission_ending(context, course)

		if not due_date or due_date <= datetime.utcnow():

			# If student check if there is a submission for the assignment
			if IQAssignment.providedBy(context):
				history = component.queryMultiAdapter((course, remoteUser),
											  		  IUsersCourseAssignmentHistory)
				if history and context.ntiid in history:  # there is a submission
					return False

			# Nothing done always strip
			return True

		return True

	@classmethod
	def strip(cls, item):
		for part in item['parts']:
			if isinstance( part, Mapping ):
				for key in ('solutions', 'explanation'):
					if key in part:
						part[key] = None

	@classmethod
	def strip_qset(cls, item):
		for q in item['questions']:
			cls.strip(q)

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return self.needs_stripped(context, self.request, self.remoteUser)

	def _do_decorate_external(self, context, result):
		for part in result['parts']:
			question_set = part['question_set']
			self.strip_qset(question_set)

class _AssignmentSubmissionPendingAssessmentBeforeDueDateSolutionStripper(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When anyone besides the instructor requests an assessed part
	within an assignment that has a due date, and we are before the
	due date, do not release the answers.

	.. note:: This is currently incomplete. We are also sending these
		question set items back 'standalone'. Depending on the UI, we
		may need to strip them there too.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			assg = component.queryUtility(IQAssignment, context.assignmentId)
			return _AssignmentBeforeDueDateSolutionStripper.needs_stripped(assg, self.request, self.remoteUser)

	def _do_decorate_external(self, context, result):
		for part in result['parts']:
			_AssignmentBeforeDueDateSolutionStripper.strip_qset(part)

@interface.implementer(IExternalObjectDecorator)
class _QuestionSetDecorator(object):

	__metaclass__ = SingletonDecorator

	def decorateExternalObject(self, original, external):
		oid = getattr(original, 'oid', None)
		if oid and OID not in external:
			external[OID] = oid

_ContextStatus = namedtuple( "_ContextStatus",
							 ("has_savepoints", "has_submissions", "is_available"))

@interface.implementer(IExternalMappingDecorator)
class _AssessmentEditorDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Give editors editing links. A subset of links should only be available for
	IQEditableEvaluations that do not have submissions. Also provide
	context on whether the evaluation has been savepointed/submitted.
	"""

	_MARKER_RELS = (VIEW_MOVE_PART, VIEW_INSERT_PART, VIEW_REMOVE_PART,
					VIEW_MOVE_PART_OPTION, VIEW_INSERT_PART_OPTION,
					VIEW_REMOVE_PART_OPTION)

	def get_courses(self, context):
		result = find_interface(context, ICourseInstance, strict=False)
		return get_courses(result)

	def _has_edit_link(self, _links):
		for lnk in _links:
			if getattr(lnk, 'rel', None) == 'edit':
				return True
		return False

	def _is_available(self, context):
		assignments = get_available_assignments_for_evaluation_object(context)
		return bool( assignments )

	def _predicate(self, context, result):
		return 		self._is_authenticated \
				and has_permission(ACT_CONTENT_EDIT, context, self.request)

	def _get_question_rels(self):
		"""
		Gather any links needed for a non-in-progress editable questions.
		"""
		return (VIEW_MOVE_PART,
				VIEW_INSERT_PART,
				VIEW_REMOVE_PART,
				VIEW_MOVE_PART_OPTION,
				VIEW_INSERT_PART_OPTION,
				VIEW_REMOVE_PART_OPTION)

	def _get_assignment_rels(self):
		"""
		Gather any links needed for a non-in-progress editable assignments.
		"""
		return (VIEW_MOVE_PART, VIEW_INSERT_PART, VIEW_REMOVE_PART)

	def _get_question_set_rels(self, context):
		"""
		Gather any links needed for a non-in-progress editable question sets.
		"""
		rels = []
		rels.append( VIEW_QUESTION_SET_CONTENTS )
		rels.append( VIEW_ASSESSMENT_MOVE )

		# Question banks cannot be (un)randomized since we may
		# support ranges.
		if not IQuestionBank.providedBy( context ):
			if IRandomizedQuestionSet.providedBy( context ):
				rels.append( VIEW_UNRANDOMIZE )
			else:
				rels.append( VIEW_RANDOMIZE )

		if IRandomizedPartsContainer.providedBy( context ):
			rels.append( VIEW_UNRANDOMIZE_PARTS )
		else:
			rels.append( VIEW_RANDOMIZE_PARTS )
		return rels

	def _get_context_status( self, context ):
		courses = self.get_courses(context)
		# We need to check assignments for our context for submissions.
		assignments = get_assignments_for_evaluation_object(context)
		savepoints = is_available = False
		for assignment in assignments:
			savepoints = savepoints or has_savepoints( assignment, courses )
			is_available = is_available or self._is_available( assignment )
		submissions = has_submissions( context, courses )
		return _ContextStatus( has_savepoints=savepoints,
							   has_submissions=submissions,
							   is_available=is_available )

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])

		context_status = self._get_context_status( context )
		in_progress = context_status.has_savepoints or context_status.has_submissions
		result['LimitedEditingCapabilities'] = in_progress
		result['LimitedEditingCapabilitiesSavepoints'] = context_status.has_savepoints
		result['LimitedEditingCapabilitiesSubmissions'] = context_status.has_submissions

		rels = ['schema',]
		# We provide the edit link no matter the status of the assessment
		# object. Some edits (textual changes) will be allowed no matter what.
		if not self._has_edit_link(_links):
			rels.append('edit')

		if not in_progress:
			# Do not provide structural links if evaluation has savepoints
			# or submissions.
			if IQuestionSet.providedBy( context ):
				qset_rels = self._get_question_set_rels( context )
				if qset_rels:
					rels.extend( qset_rels )
				# For question sets, we also want to decorate our randomized state.
				if not IQuestionBank.providedBy( context ):
					result['Randomized'] = IRandomizedQuestionSet.providedBy( context )
				result['RandomizedParts'] = IRandomizedPartsContainer.providedBy( context )
			elif IQAssignment.providedBy( context ):
				rels.extend( self._get_assignment_rels() )
			elif IQuestion.providedBy( context ):
				rels.extend( self._get_question_rels() )

		for rel in rels:
			if rel in self._MARKER_RELS:
				elements = None
			else:
				elements = ('@@%s' % rel,)
			link = Link(context, rel=rel, elements=elements)
			interface.alsoProvides(link, ILocation)
			link.__name__ = ''
			link.__parent__ = context
			_links.append(link)

@interface.implementer(IExternalMappingDecorator)
class _PartAutoGradeStatus(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Mark question parts as auto-gradable.
	"""

	def _predicate(self, context, result):
		# IQParts are not IQEditableEvaluations (we can check lineage if needed).
		return 		self._is_authenticated \
				and has_permission(ACT_CONTENT_EDIT, context, self.request) \

	def _do_decorate_external(self, context, result):
		result['AutoGradable'] = is_part_auto_gradable( context )

@interface.implementer(IExternalMappingDecorator)
class _AssessmentDateEditLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Give editors a date-edit link. This should be available on all
	assignments/inquiries.
	"""

	def _predicate(self, context, result):
		return 		self._is_authenticated \
				and has_permission(ACT_CONTENT_EDIT, context, self.request)

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])
		link = Link(context, rel='date-edit')
		interface.alsoProvides(link, ILocation)
		link.__name__ = ''
		link.__parent__ = context
		_links.append(link)

@interface.implementer(IExternalMappingDecorator)
class _AssessmentPracticeLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Give editors and instructors the practice submission link.
	"""

	def _predicate(self, context, result):
		user = self.remoteUser
		course = _get_course_from_evaluation(context, user, request=self.request)
		return 		self._is_authenticated \
				and (	is_course_instructor_or_editor(course, user) \
					 or has_permission(ACT_CONTENT_EDIT, context, self.request))

	def _do_decorate_external(self, context, result):
		_links = result.setdefault(LINKS, [])
		link = Link(context, rel=ASSESSMENT_PRACTICE_SUBMISSION,
					elements=(ASSESSMENT_PRACTICE_SUBMISSION,))
		interface.alsoProvides(link, ILocation)
		link.__name__ = ''
		link.__parent__ = context
		_links.append(link)
