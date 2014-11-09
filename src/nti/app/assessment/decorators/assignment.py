#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from datetime import datetime

import repoze.lru

from zope import component
from zope import interface

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssignmentDateContext

from nti.contentlibrary.externalization import root_url_of_unit

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseInstanceVendorInfo

from nti.dataserver.links import Link
from nti.dataserver.traversal import find_interface

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.utils.property import Lazy

from .._utils import assignment_download_precondition

from ..interfaces import ACT_VIEW_SOLUTIONS

from . import _get_course_from_assignment
from . import _AbstractTraversableLinkDecorator
		
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
		by outline ode links
		"""
		## TODO: We will remove when a preference course/user? policy is in place.
		vendor_info = ICourseInstanceVendorInfo(course, {})
		try:
			result = vendor_info['NTI']['show_assignments_by_outline']
		except (TypeError, KeyError):
			result = True
		return result
	
	def _do_decorate_external(self, context, result_map):
		course = ICourseInstance(context, context)
		if not self.show_links(course):
			return
		
		links = result_map.setdefault( LINKS, [] )
		for rel in ('AssignmentsByOutlineNode', 'NonAssignmentAssessmentItemsByOutlineNode'):
			# Prefer to canonicalize these through to the course, if possible
			link = Link( course,
						 rel=rel,
						 elements=(rel,),
						 # We'd get the wrong type/ntiid values if we
						 # didn't ignore them.
						 ignore_properties_of_target=True)
			links.append(link)

class _AssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an instructor feteches an assignment that contains a file part
	somewhere, provide access to the link do download it.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return assignment_download_precondition(context, self.request, self.remoteUser) # XXX Hack

	def _do_decorate_external(self, context, result):
		links = result.setdefault( LINKS, [] )
		links.append( Link( context,
							rel='ExportFiles',
							elements=('BulkFilePartDownload',) ) )

class _AssignmentSectionOverrides(AbstractAuthenticatedRequestAwareDecorator):
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
		
		dates = IQAssignmentDateContext(course).of(assignment)
		for k in ('available_for_submission_ending',
				  'available_for_submission_beginning'):
			asg_date = getattr(assignment, k)
			dates_date = getattr(dates, k)
			if dates_date != asg_date:
				result[k] = to_external_object(dates_date)
		
		policy = IQAssignmentPolicies(course).getPolicyForAssignment(assignment.ntiid)
		if policy and 'maximum_time_allowed' in policy:
			result['maximum_time_allowed' ] = policy['maximum_time_allowed']

@repoze.lru.lru_cache(1000, timeout=3600)
def _root_url(ntiid):
	library = component.queryUtility(IContentPackageLibrary)
	if ntiid and library is not None:
		paths = library.pathToNTIID(ntiid)
		package = paths[0] if paths else None
		try:
			result = root_url_of_unit(package) if package is not None else None
			return result
		except StandardError:
			pass
	return None

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
		course = None
		if context is not None:
			course = _get_course_from_assignment(context, remoteUser)
			if course is not None:
				due_date = IQAssignmentDateContext(course).of(context).available_for_submission_ending
			else:
				due_date = context.available_for_submission_ending
		if not due_date or due_date <= datetime.utcnow():
			# No due date, nothing to do
			# Past the due date, nothing to do
			return False

		if course is None:
			logger.warn("could not adapt %s to course", context)
			return False

		if has_permission(ACT_VIEW_SOLUTIONS, course, request):
			# The instructor, nothing to do
			return False

		return True

	@classmethod
	def strip(cls,item):
		_cls = item.get('Class')
		if _cls in ('Question','AssessedQuestion'):
			for part in item['parts']:
				part['solutions'] = None
				part['explanation'] = None
		elif _cls in ('QuestionSet','AssessedQuestionSet'):
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
					