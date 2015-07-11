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

from nti.externalization.interfaces import LocatedExternalDict

from ..common import get_course_from_assignment

from ..metadata import UsersCourseAssignmentMetadataItem

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

	def _validate(self):
		creator = self.remoteUser
		if not creator:
			raise hexc.HTTPForbidden("Must be Authenticated")
		try:
			course = get_course_from_assignment(self.context, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")
		except RequiredMissing:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

		return creator, course

	def _process(self, creator=None, course=None, item=None):
		if creator is None or course is None:
			creator, course = self._validate()

		item = self.readCreateUpdateContentObject(creator) if item is None else item
		lifecycleevent.created(item)

		self.request.response.status_int = 201

		assignmentId = self.context.ntiid
		metadata = component.getMultiAdapter((course, creator),
											 IUsersCourseAssignmentMetadata)
		item.containerId = assignmentId
		result = metadata.append(assignmentId, item)
		return result

	def _do_call(self):
		return self._process()

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='POST',
			 permission=nauth.ACT_READ,
			 name="Commence")
class AssignmentSubmissionStartPostView(AssignmentSubmissionMetataPostView):

	def _do_call(self):
		creator, course = self._validate()
		container = component.getMultiAdapter((course, creator),
												IUsersCourseAssignmentMetadata)
		try:
			item = container[self.context.ntiid]
		except KeyError:
			item = UsersCourseAssignmentMetadataItem()
			self._process(creator=creator, course=course, item=item)
		if not item.StartTime:
			item.StartTime = time.time()
		# return assignment
		return self.context

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="Metadata")
class AssignmentSubmissionMetadataGetView(AbstractAuthenticatedView):

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

		container = component.getMultiAdapter((course, creator),
												IUsersCourseAssignmentMetadata)

		result = container[self.context.ntiid]
		return result

	def __call__(self):
		try:
			result = self._do_call()
			return result
		except KeyError:
			return hexc.HTTPNotFound()

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 request_method='GET',
			 permission=nauth.ACT_READ,
			 name="StartTime")
class AssignmentSubmissionStartGetView(AssignmentSubmissionMetadataGetView):

	def __call__(self):
		try:
			item = self._do_call()
			result = LocatedExternalDict({'StartTime': item.StartTime})
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

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject
