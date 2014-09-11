#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver import authorization as nauth

from ..interfaces import IUsersCourseAssignmentSavepoint
from ..interfaces import IUsersCourseAssignmentSavepoints
from ..interfaces import IUsersCourseAssignmentSavepointItem

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='POST',
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
		course = component.queryMultiAdapter( (self.context, creator),
											  ICourseInstance)
		if course is None:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

		submission = self.readCreateUpdateContentObject(creator)
		
		assignment = component.queryUtility(IQAssignment, name=submission.assignmentId)
		if not assignment:
			hexc.HTTPUnprocessableEntity("Assignment not found")
			
		savepoint = component.getMultiAdapter( (course, submission.creator),
												IUsersCourseAssignmentSavepoint)
		submission.containerId = submission.assignmentId

		self.request.response.status_int = 201
		
		# Now record the submission.
		result = savepoint.recordSubmission(submission)
		return result

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseAssignmentSavepoints,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class AssignmentSavepointGetView(AbstractAuthenticatedView):
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

	def _do_delete_object( self, theObject ):
		del theObject.__parent__[theObject.__name__]
		return theObject
