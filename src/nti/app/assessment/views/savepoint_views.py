#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from . import MessageFactory as _

import time

from zope import component
from zope import interface

from zope.schema.interfaces import RequiredMissing

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment.views import get_ds2

from nti.app.assessment._submission import get_source
from nti.app.assessment._submission import check_upload_files
from nti.app.assessment._submission import read_multipart_sources

from nti.app.assessment.common import get_course_from_assignment
from nti.app.assessment.common import get_assessment_metadata_item

from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepointItem

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.internalization import read_input_data
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.renderers.interfaces import INoHrefInResponse

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.dataserver import authorization as nauth

from nti.externalization.oids import to_external_ntiid_oid
from nti.externalization.externalization import to_external_object

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
			raise hexc.HTTPForbidden(_("Must be Authenticated."))
		try:
			course = get_course_from_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden(_("Must be enrolled in a course."))
		except RequiredMissing:
			raise hexc.HTTPForbidden(_("Must be enrolled in a course."))

		# No savepoints unless the timed assignment has been started
		if IQTimedAssignment.providedBy(self.context):
			item = get_assessment_metadata_item(course,
												self.remoteUser,
												self.context.ntiid)
			if item is None or not item.StartTime:
				raise hexc.HTTPClientError(_("Cannot savepoint timed assignment unless started."))

		if not self.request.POST:
			submission = self.readCreateUpdateContentObject(creator)
			check_upload_files(submission)
		else:
			extValue = get_source(self.request, 'json', 'input', 'submission')
			if not extValue:
				raise hexc.HTTPUnprocessableEntity(_("No submission source was specified."))
			extValue = extValue.read()
			extValue = read_input_data(extValue, self.request)
			submission = self.readCreateUpdateContentObject(creator,
															externalValue=extValue)
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
		result = recorded = savepoint.recordSubmission(submission)
		result = to_external_object(result)
		result['href'] = "/%s/Objects/%s" % (get_ds2(self.request),
											 to_external_ntiid_oid(recorded))
		interface.alsoProvides(result, INoHrefInResponse)
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
			raise hexc.HTTPForbidden(_("Must be Authenticated."))
		try:
			course = get_course_from_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden(_("Must be enrolled in a course."))
		except RequiredMissing:
			raise hexc.HTTPForbidden(_("Must be enrolled in a course."))

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
