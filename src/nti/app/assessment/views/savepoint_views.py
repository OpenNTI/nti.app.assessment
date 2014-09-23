#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope.schema.interfaces import RequiredMissing

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.dataserver import authorization as nauth

from .._utils import find_course_for_assignment

from ..interfaces import IUsersCourseAssignmentSavepoint
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
			course = find_course_for_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")
		
		submission = self.readCreateUpdateContentObject(creator)
			
		savepoint = component.getMultiAdapter( (course, submission.creator),
												IUsersCourseAssignmentSavepoint)
		submission.containerId = submission.assignmentId

		self.request.response.status_int = 201
		
		# Now record the submission.
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
			course = find_course_for_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")
				
		savepoint = component.getMultiAdapter( (course, creator),
												IUsersCourseAssignmentSavepoint)
		try:
			result = savepoint[self.context.ntiid]
			return result
		except KeyError:
			return hexc.HTTPNotFound()

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentSavepointItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentSavepointItemDeleteView(UGDDeleteView):

	def _do_delete_object( self, theObject ):
		del theObject.__parent__[theObject.__name__]
		return theObject
