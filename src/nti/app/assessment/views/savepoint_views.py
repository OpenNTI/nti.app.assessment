#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import component
from zope.schema.interfaces import RequiredMissing

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQTimedAssignment

from nti.dataserver import authorization as nauth

from ..common import get_course_from_assignment
from ..common import get_assessment_metadata_item

from .._submission import get_source
from .._submission import check_upload_files
from .._submission import read_multipart_sources

from ..interfaces import IUsersCourseAssignmentMetadata
from ..interfaces import IUsersCourseAssignmentSavepoint
from ..interfaces import IUsersCourseAssignmentSavepoints
from ..interfaces import IUsersCourseAssignmentSavepointItem

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='POST',
			 permission=nauth.ACT_READ,
			 name="Savepoint")
class AssignmentSubmissionSavepointPostView(AbstractAuthenticatedView,
								   			ModeledContentUploadRequestUtilsMixin):
	"""
	Students can POST to the assignment to create their save point
	"""

	_EXTRA_INPUT_ERRORS = \
			ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + (AttributeError,)

	content_predicate = IQAssignmentSubmission.providedBy

	def _do_call(self):
		creator = self.remoteUser
		if not creator:
			raise hexc.HTTPForbidden("Must be Authenticated")
		try:
			course = get_course_from_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

		# No savepoints unless the timed assignment has been started
		if IQTimedAssignment.providedBy(self.context):
			item = get_assessment_metadata_item(course, self.remoteUser, self.context.ntiid)
			if item is None or not item.StartTime:
				raise hexc.HTTPClientError("Cannot savepoint timed assignment unless started.")

		if not self.request.POST:
			submission = self.readCreateUpdateContentObject(creator)
			check_upload_files(submission)
		else:
			extValue = get_source(self.request, 'json', 'input', 'submission')
			if not extValue:
				raise hexc.HTTPUnprocessableEntity("No submission source was specified")
			extValue = self.readInput(value=extValue.read())
			submission = self.readCreateUpdateContentObject(creator, externalValue=extValue)
			submission = read_multipart_sources(submission, self.request)

		savepoint = component.getMultiAdapter((course, submission.creator),
												IUsersCourseAssignmentSavepoint)
		submission.containerId = submission.assignmentId

		# for legacy purposes we assume the start time as the first savepoint submitted
		metadata = component.getMultiAdapter((course, submission.creator),
											  IUsersCourseAssignmentMetadata)
		metadata.get_or_create(submission.assignmentId, time.time())

		# Now record the submission.
		self.request.response.status_int = 201
		result = savepoint.recordSubmission(submission)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Savepoint")
class AssignmentSubmissionSavepointGetView(AbstractAuthenticatedView):

	def __call__(self):
		creator = self.remoteUser
		if not creator:
			raise hexc.HTTPForbidden("Must be Authenticated")
		try:
			course = get_course_from_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

		savepoint = component.getMultiAdapter((course, creator),
												IUsersCourseAssignmentSavepoint)
		try:
			result = savepoint[self.context.ntiid]
			return result
		except KeyError:
			return hexc.HTTPNotFound()

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseAssignmentSavepoints,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class AssignmentSavepointsGetView(AbstractAuthenticatedView):
	"""
	Students can view their assignment save points as ``path/to/course/AssignmentSavepoints``
	"""

	def __call__(self):
		savepoints = self.request.context
		return savepoints

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentSavepointItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentSavepointItemDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject
