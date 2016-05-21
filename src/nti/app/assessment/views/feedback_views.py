#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from functools import partial

from zope import component
from zope import interface

from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer

from nti.app.authentication import get_remote_user

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentfile import validate_sources
from nti.app.contentfile import get_content_files
from nti.app.contentfile import read_multipart_sources
from nti.app.contentfile import transfer_internal_content_data

from nti.app.contentlibrary import LIBRARY_PATH_GET_VIEW
from nti.app.contentlibrary.views.library_views import AbstractCachingLibraryPathView

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.interfaces import INewObjectTransformer

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.dataserver import authorization as nauth

from nti.externalization.oids import to_external_oid

from nti.traversal.traversal import find_interface

@interface.implementer(INewObjectTransformer)
@component.adapter(IRequest, IUsersCourseAssignmentHistoryItemFeedback)
def _feedback_transformer_factory(request, context):
	result = partial(_feedback_transformer, request)
	return result

@interface.implementer(IExceptionResponse)
@component.adapter(IRequest, IUsersCourseAssignmentHistoryItemFeedback)
def _feedback_transformer(request, context):
	sources = get_content_files(context)
	if sources and request and request.POST:
		read_multipart_sources(request, sources.values())
	if sources:
		validate_attachments(get_remote_user(), context, sources.values())
	return context

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItemFeedbackContainer,
			 renderer='rest',
			 permission=nauth.ACT_CREATE,
			 request_method='POST')
class AsssignmentHistoryItemFeedbackPostView(AbstractAuthenticatedView,
											 ModeledContentUploadRequestUtilsMixin):
	"""
	Students/faculty can POST to the history item's Feedback collection
	to create a feedback node.

	The ACL will limit this to the student himself and the teacher(s) of the
	course.

	.. note:: The ACL is not currently implemented.
	"""

	content_predicate = IUsersCourseAssignmentHistoryItemFeedback

	def _do_call(self):
		creator = self.remoteUser
		feedback = self.readCreateUpdateContentObject(creator)
		self.request.context['ignored'] = feedback

		_feedback_transformer(self.request, feedback)

		self.request.response.status_int = 201
		# TODO: Shouldn't this be the external NTIID?
		# This is what ugd_edit_views does though
		self.request.response.location = \
				self.request.resource_url(creator,
										  'Objects',
										  to_external_oid(feedback))
		return feedback

@view_config(context=IUsersCourseAssignmentHistoryItemFeedback)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_UPDATE,
			   request_method='PUT')
class AssignmentHistoryItemFeedbackPutView(UGDPutView):

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		result = UGDPutView.updateContentObject(self,
												contentObject=contentObject,
												externalValue=externalValue,
												set_id=set_id,
												notify=notify)
		sources = transfer_internal_content_data(contentObject,
												 request=self.request,
												 ownership=False)
		if sources:
			validate_attachments(self.remoteUser, contentObject, sources)
		return result

def validate_attachments(user, context, sources=()):
	sources = sources or ()

	# check source contraints
	validate_sources(user, context, sources)

	# take ownership
	for source in sources:
		source.__parent__ = context

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItemFeedback,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentHistoryItemFeedbackDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IUsersCourseAssignmentHistoryItemFeedback,
			 name=LIBRARY_PATH_GET_VIEW,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class _FeedbackLibraryPathView(AbstractCachingLibraryPathView):
	"""
	For feedback items, getting the path traversal can
	be accomplished through lineage.
	"""

	def __call__(self):
		results = []
		course = course_from_context_lineage( self.context )
		if course is not None:
			history_item = find_interface( self.context, IUsersCourseAssignmentHistoryItem )
			path = (course, history_item, self.context)
			results.append( path )
		return results
