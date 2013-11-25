#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment.

$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope.container.contained import Contained
from zope.location.interfaces import LocationError

from numbers import Number

import pyramid.httpexceptions as hexc
from pyramid.interfaces import IRequest
from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.utils.property import alias

from nti.dataserver import authorization as nauth

# TODO: Break these direct dependencies....
from nti.appserver.contentlibrary.library_views import PAGE_INFO_MT_JSON
# ... this in particular could be a view.
from nti.appserver.contentlibrary.library_views import find_page_info_view_helper

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer
from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.appserver.interfaces import IContainerCollection


####
## In pyramid 1.4, there is some minor wonkiness with the accept= request predicate.
## Your view can get called even if no Accept header is present if all the defined
## views include a non-matching accept predicate. Stil, this is much better than
## the behaviour under 1.3.
####
_read_view_defaults = dict( route_name='objects.generic.traversal',
							renderer='rest',
							permission=nauth.ACT_READ,
							request_method='GET' )
_question_view = dict(context=IQuestion)
_question_view.update(_read_view_defaults)

_assignment_view = dict(context=IQAssignment)
_assignment_view.update(_read_view_defaults)


@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_assignment_view)
def pageinfo_from_question_view( request ):
	assert request.accept
	# questions are now generally held within their containing IContentUnit,
	# but some old tests don't parent them correctly, using strings
	content_unit_or_ntiid = request.context.__parent__
	return find_page_info_view_helper( request, content_unit_or_ntiid )


@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_question_view )
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_assignment_view )
def get_question_view_link( request ):
	# Not supported.
	return hexc.HTTPBadRequest()

@view_config(accept=str(''), 	# explicit empty accept, else we get a ConfigurationConflict
			 **_question_view)	# and/or no-Accept header goes to the wrong place
@view_config(**_question_view)
@view_config(accept=str(''),
			 **_assignment_view)
@view_config(**_assignment_view)
def get_question_view( request ):
	return request.context

del _read_view_defaults
del _question_view
del _assignment_view

from nti.appserver._view_utils import AbstractAuthenticatedView
from nti.appserver._view_utils import ModeledContentUploadRequestUtilsMixin
from pyramid.interfaces import IExceptionResponse

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 permission=nauth.ACT_CREATE,
			 request_method='POST')
class AssignmentSubmissionPostView(AbstractAuthenticatedView,
								   ModeledContentUploadRequestUtilsMixin):
	"""
	Students can POST to the assignment to create their submission.

	The ACL on an assignment will generally limit this to people that
	are enrolled in the course.

	.. note:: The ACL is currently not implemented; a test will fail when it is.

	"""

	content_predicate = IQAssignmentSubmission.providedBy

	def _do_call(self):
		creator = self.remoteUser

		submission = self.readCreateUpdateContentObject(creator)
		# Re-use the same code for putting to a user
		return component.getMultiAdapter( (self.request, submission),
										  IExceptionResponse)


@view_defaults(route_name="objects.generic.traversal",
			   renderer='rest',
			   context=IUsersCourseAssignmentHistory,
			   permission=nauth.ACT_READ,
			   request_method='GET')
class AssignmentHistoryGetView(AbstractAuthenticatedView):
	"""
	Students can view their assignment history as ``path/to/course/AssignmentHistory``
	"""

	def __call__(self):
		history = self.request.context
		return history

from zope.container.traversal import ContainerTraversable
@component.adapter(IUsersCourseAssignmentHistory,IRequest)
class AssignmentHistoryRequestTraversable(ContainerTraversable):
	def __init__(self, context, request):
		ContainerTraversable.__init__(self,context)

	def traverse(self, name, further_path):
		if name == 'lastViewed':
			raise LocationError(self._container, name)
		return ContainerTraversable.traverse(self, name, further_path)

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseAssignmentHistory,
			 permission=nauth.ACT_UPDATE,
			 request_method='PUT',
			 name='lastViewed')
class AssignmentHistoryLastViewedPutView(AbstractAuthenticatedView,
										 ModeledContentUploadRequestUtilsMixin):
	"""
	Given an assignment history, a student can change the lastViewed
	by PUTting to it.

	Currently this is a named view; if we wanted to use the field traversing
	support, we would need to register an ITraversable subclass for this object
	that extends _AbstractExternalFieldTraverser.
	"""

	inputClass = Number

	def _do_call(self):
		ext_input = self.readInput()
		history = self.request.context
		self.request.context.lastViewed = ext_input
		return history


from nti.externalization.oids import to_external_oid
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

		self.request.response.status_int = 201
		# TODO: Shouldn't this be the external NTIID? This is what ugd_edit_views does though
		self.request.response.location = self.request.resource_url( creator,
																	'Objects',
																	to_external_oid( feedback ) )

		return feedback
