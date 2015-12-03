#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from datetime import datetime

from zope import component
from zope import interface

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssignmentDateContext

from nti.common.property import Lazy

from nti.contentlibrary.interfaces import IContentUnit

from nti.contenttypes.courses import get_course_vendor_info

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import is_course_instructor

from nti.externalization.singleton import SingletonDecorator
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import IExternalObjectDecorator
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.links.links import Link

from nti.traversal.traversal import find_interface

from ..common import get_assessment_metadata_item
from ..common import get_available_for_submission_ending
from ..common import get_available_for_submission_beginning

from .._utils import assignment_download_precondition

from ..interfaces import ACT_VIEW_SOLUTIONS
from ..interfaces import IUsersCourseAssignmentHistory

from . import _root_url
from . import _get_course_from_assignment
from . import _AbstractTraversableLinkDecorator

OID = StandardExternalFields.OID
LINKS = StandardExternalFields.LINKS

@interface.implementer(IExternalMappingDecorator)
class _AssignmentsByOutlineNodeDecorator(_AbstractTraversableLinkDecorator):
	"""
	For things that have a assignments, add this
	as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor. Those registrations are more general,
	# though, because we try to always go through a course, if possible
	# (because of issues resolving really old enrollment records), although
	# the enrollment record is a better place to go because it has the username
	# in the path

	def show_links(self, course):
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

	def _do_decorate_external(self, context, result_map):
		course = ICourseInstance(context, context)
		if not self.show_links(course):
			return

		links = result_map.setdefault(LINKS, [])
		for rel in ('AssignmentsByOutlineNode', 'NonAssignmentAssessmentItemsByOutlineNode'):
			# Prefer to canonicalize these through to the course, if possible
			link = Link(course,
						 rel=rel,
						 elements=(rel,),
						 # We'd get the wrong type/ntiid values if we
						 # didn't ignore them.
						 ignore_properties_of_target=True)
			links.append(link)

class _AssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an instructor fetches an assignment that contains a file part
	somewhere, provide access to the link do download it.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return assignment_download_precondition(context, self.request, self.remoteUser)  # XXX Hack

	def _do_decorate_external(self, context, result):
		# TODO It would be better to have the course context in our link,
		# but for now, we'll just have a course param.
		course = _get_course_from_assignment(context, self.remoteUser)
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
	When an assignment is externalized, check for overrides
	"""

	@Lazy
	def _catalog(self):
		result = component.getUtility(ICourseCatalog)
		return result

	def _do_decorate_external(self, assignment, result):
		course = _get_course_from_assignment(assignment, self.remoteUser, self._catalog)
		if course is None:
			return

		# Do not override dates if locked.
		start_date = get_available_for_submission_beginning( assignment, course )
		end_date = get_available_for_submission_ending( assignment, course )
		result['available_for_submission_ending'] = to_external_object( start_date )
		result['available_for_submission_beginning'] = to_external_object( end_date )

		if not IQTimedAssignment.providedBy(assignment):
			result['IsTimedAssignment'] = False
			return

		max_time_allowed = assignment.maximum_time_allowed
		policy = IQAssignmentPolicies(course).getPolicyForAssignment(assignment.ntiid)
		if 	policy and 'maximum_time_allowed' in policy and \
			policy['maximum_time_allowed'] != max_time_allowed:
			max_time_allowed = policy['maximum_time_allowed']

		result['IsTimedAssignment'] = True
		result['MaximumTimeAllowed'] = result['maximum_time_allowed' ] = max_time_allowed

class _TimedAssignmentPartStripperDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, context, result):
		course = _get_course_from_assignment(context, user=self.remoteUser)
		if course is None or is_course_instructor(course, self.remoteUser):
			return
		item = get_assessment_metadata_item(course, self.remoteUser, context.ntiid)
		if item is None or not item.StartTime:
			result['parts'] = None

class _AssignmentMetadataDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _do_decorate_external(self, context, result):
		course = _get_course_from_assignment(context, user=self.remoteUser)
		if course is None:
			return
		if is_course_instructor(course, self.remoteUser):
			return
		item = get_assessment_metadata_item(course, self.remoteUser, context.ntiid)
		if item is not None:
			result['Metadata'] = {'Duration': item.Duration,
								  'StartTime': item.StartTime}


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
			result['ContentRoot' ] = bucket_root

class _AssignmentBeforeDueDateSolutionStripper(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When anyone besides the instructor requests an assignment
	that has a due date, and we are before the due date,
	do not release the answers.

	.. note:: This is currently incomplete. We are also sending these
		question set items back 'standalone'. Depending on the UI, we
		may need to strip them there too.
	"""

	@classmethod
	def needs_stripped(cls, context, request, remoteUser):
		due_date = None
		if context is not None:
			course = _get_course_from_assignment(context, remoteUser)
		else:
			course = None

		if context is not None:
			if course is not None:
				dates = IQAssignmentDateContext(course)
				due_date = dates.of(context).available_for_submission_ending
			else:
				due_date = context.available_for_submission_ending

		if not due_date or due_date <= datetime.utcnow():

			if course is not None and is_course_instructor(course, remoteUser):
				return False

			# if student check if there is a submission for the assignment
			if course is not None and IQAssignment.providedBy(context):
				history = component.queryMultiAdapter((course, remoteUser),
											  		  IUsersCourseAssignmentHistory)
				if history and context.ntiid in history:  # there is a submission
					return False

			# Nothing done always strip
			return True

		if course is None:
			logger.warn("could not adapt %s to course", context)
			return False

		if has_permission(ACT_VIEW_SOLUTIONS, course, request):
			# The instructor, nothing to do
			return False

		return True

	@classmethod
	def strip(cls, item):
		clazz = item.get('Class')
		if clazz in ('Question', 'AssessedQuestion'):
			for part in item['parts']:
				part['solutions'] = None
				part['explanation'] = None
		elif clazz in ('QuestionSet', 'AssessedQuestionSet'):
			for q in item['questions']:
				cls.strip(q)

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return self.needs_stripped(context, self.request, self.remoteUser)

	def _do_decorate_external(self, context, result):
		for part in result['parts']:
			question_set = part['question_set']
			self.strip(question_set)

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
			_AssignmentBeforeDueDateSolutionStripper.strip(part)

@interface.implementer(IExternalObjectDecorator)
class _QuestionSetDecorator(object):

	__metaclass__ = SingletonDecorator

	def decorateExternalObject(self, original, external):
		oid = getattr(original, 'oid', None)
		if oid and OID not in external:
			external[OID] = oid
