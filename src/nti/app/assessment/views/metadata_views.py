#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id: savepoint_views.py 50902 2014-10-10 01:41:39Z carlos.sanchez $
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import lifecycleevent
from zope.schema.interfaces import RequiredMissing

from pyramid.view import view_config
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQAssignment

from nti.dataserver import authorization as nauth

from .._utils import find_course_for_assignment

from ..interfaces import IUsersCourseAssignmentMetadata
from ..interfaces import IUsersCourseAssignmentMetadataItem
from ..interfaces import IUsersCourseAssignmentMetadataContainer

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='POST',
			 permission=nauth.ACT_READ,
			 name="Metadata")
class AssignmentSubmissionMetataPostView(AbstractAuthenticatedView,
								   		 ModeledContentUploadRequestUtilsMixin):

	_EXTRA_INPUT_ERRORS = \
			ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + (AttributeError,)

	content_predicate = IUsersCourseAssignmentMetadataItem.providedBy

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
		
		item = self.readCreateUpdateContentObject(creator)
		lifecycleevent.created(item)
		
		self.request.response.status_int = 201
				
		assignmentId = self.context.ntiid
		metadata = component.getMultiAdapter( (course, creator),
											  IUsersCourseAssignmentMetadata)
		item.containerId = assignmentId	
		result = metadata.append(assignmentId, item)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Metadata")
class AssignmentSubmissionMetadataGetView(AbstractAuthenticatedView):
	
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
				
		container = component.getMultiAdapter( (course, creator),
												IUsersCourseAssignmentMetadata)
		try:
			result = container[self.context.ntiid]
			return result
		except KeyError:
			return hexc.HTTPNotFound()

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseAssignmentMetadataContainer,
			 permission=nauth.ACT_READ,
			 request_method='GET')
class AssignmentMetadataGetView(AbstractAuthenticatedView):
	"""
	Students can view their assignment metadata  as ``path/to/course/AssignmentMetadata``
	"""

	def __call__(self):
		container = self.request.context
		return container

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentMetadataItem,
			 renderer='rest',
			 permission=nauth.ACT_UPDATE,
			 request_method='PUT')
class AssignmentMetadataItemPutView(UGDPutView):
	pass

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentMetadataItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentMetadataItemDeleteView(UGDDeleteView):

	def _do_delete_object( self, theObject ):
		del theObject.__parent__[theObject.__name__]
		return theObject
