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

from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedbackFileConstraints

from nti.app.authentication import get_remote_user

from nti.app.contentfile import file_contraints
from nti.app.contentfile import validate_sources
from nti.app.contentfile import get_content_files
from nti.app.contentfile import read_multipart_sources
from nti.app.contentfile import transfer_internal_content_data

from nti.appserver.interfaces import INewObjectTransformer

from nti.appserver.ugd_edit_views import UGDPutView

from nti.dataserver import authorization as nauth

from nti.namedfile.file import FileConstraints

@component.adapter(IRequest, IUsersCourseAssignmentHistoryItemFeedback)
@interface.implementer(INewObjectTransformer)
def _feedback_transformer_factory(request, context):
	result = partial(_feedback_transformer, request)
	return result

@component.adapter(IRequest, IUsersCourseAssignmentHistoryItemFeedback)
@interface.implementer(IExceptionResponse)
def _feedback_transformer(request, context):
	sources = get_content_files(context)
	if sources and request and request.POST:
		read_multipart_sources(request, sources.values())
	if sources:
		validate_attachments(get_remote_user(), context, sources.values())
	return context

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
	validate_sources(user, 
					 context,
					 sources, 
					 constraint=IUsersCourseAssignmentHistoryItemFeedbackFileConstraints)

	# check max files to upload
	constraints = file_contraints(
					user=user,
					context=context,
					constraint=IUsersCourseAssignmentHistoryItemFeedbackFileConstraints)
	if constraints is not None and len(sources) > constraints.max_files:
		raise ConstraintNotSatisfied(len(sources), 'max_files')
	
	# take ownership
	for source in sources:
		source.__parent__ = context

@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
@interface.implementer(IUsersCourseAssignmentHistoryItemFeedbackFileConstraints)
class _AssignmentHistoryItemFeedbackFileConstraints(FileConstraints):
	max_files = 5
	max_file_size = 10000000 # 10 MB
