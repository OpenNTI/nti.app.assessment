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

import pyramid.httpexceptions as hexc
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


@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name="objects.generic.traversal",
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='AssignmentHistory')
class AssignmentHistoryGetView(AbstractAuthenticatedView):
	"""
	Students can view their assignment history as ``path/to/course/AssignmentHistory``
	"""

	# Note the view_config above overlaps with things in decorators.

	@interface.implementer(IContainerCollection)
	class _HistoryCollection(Contained):
		"We use a collection for the purposes of externalization. That may not last too long."
		name = alias('__name__')
		accepts = ()
		def __init__(self, container):
			self.container = container


	def __call__(self):
		user = self.remoteUser
		course = ICourseInstance(self.request.context)
		history = component.getMultiAdapter( (course, user),
											 IUsersCourseAssignmentHistory )

		collection = self._HistoryCollection(history)
		collection.__parent__ = self.request.context
		collection.__name__ = self.request.view_name

		return collection
