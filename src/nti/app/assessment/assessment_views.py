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
from zope.location.interfaces import LocationError

from numbers import Number

import pyramid.httpexceptions as hexc
from pyramid.interfaces import IRequest
from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.dataserver import authorization as nauth

# TODO: Break these direct dependencies....
from nti.appserver.contentlibrary.library_views import PAGE_INFO_MT_JSON
from nti.appserver.contentlibrary.library_views import PAGE_INFO_MT
# ... this in particular could be a view.
from nti.appserver.contentlibrary.library_views import find_page_info_view_helper

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer
from .interfaces import IUsersCourseAssignmentHistoryItemFeedback


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

_question_set_view = dict(context=IQuestionSet)
_question_set_view.update(_read_view_defaults)

_assignment_view = dict(context=IQAssignment)
_assignment_view.update(_read_view_defaults)


@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_assignment_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT),
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
			 **_question_set_view )
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_assignment_view )
def get_question_view_link( request ):
	# Not supported.
	return hexc.HTTPBadRequest()

@view_config(accept=str(''), 	# explicit empty accept, else we get a ConfigurationConflict
			 **_question_view)	# and/or no-Accept header goes to the wrong place
@view_config(**_question_view)
@view_config(accept=str(''),
			 **_question_set_view)
@view_config(**_question_set_view)
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

from cStringIO import StringIO
from zipfile import ZipFile
from zipfile import ZipInfo
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.assessment.interfaces import IQUploadedFile
from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQFilePart


from nti.contenttypes.courses.interfaces import is_instructed_by_name

from nti.appserver.pyramid_authorization import has_permission

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 #permission=nauth.ACT_READ, # Permissioning handled manually...
			 request_method='GET',
			 name='BulkFilePartDownload')
class AssignmentSubmissionBulkFileDownloadView(AbstractAuthenticatedView):
	"""
	A view that returns a ZIP file containing all
	the files submitted by any student in the course for
	any file part in the given assignment.

	The ZIP has the following structure::

	<student-username>/
		<part-num>/
			<question-num>/
				<submitted-file-name>

	.. note:: An easy extension to this would be to accept
		a query param giving a list of usernames to include.

	.. note:: The current implementation does not stream;
		the entire ZIP is buffered (potentially in memory) before being
		transmitted. Streaming while building a ZIP is somewhat
		complicated in the ZODB/WSGI combination. It may be possible
		to do something with app_iter and stream in \"chunks\".
	"""

	@classmethod
	def _precondition(cls, context, request):
		username = request.authenticated_userid
		if not username:
			return False
		course = ICourseInstance(context)
		if not is_instructed_by_name(course, username) and not has_permission(nauth.ACT_MODERATE, context, request):
			# We allow global admins in too for testing
			return False

		# Does it have a file part?
		for assignment_part in context.parts:
			question_set = assignment_part.question_set
			for question in question_set.questions:
				for question_part in question.parts:
					if IQFilePart.providedBy(question_part):
						return True # TODO: Consider caching this?

	def __call__(self):
		# We're assuming we'll find some submitted files.
		# What should we do if we don't?
		context = self.request.context
		request = self.request
		assignment_id = context.__name__
		course = ICourseInstance(context)
		enrollments = ICourseEnrollments(course)

		username = self.request.authenticated_userid

		if not self._precondition(context, request):
			raise hexc.HTTPForbidden()

		buf = StringIO()
		zipfile = ZipFile( buf, 'w' )
		for principal in enrollments.iter_enrollments():
			assignment_history = component.getMultiAdapter( (course, principal),
															IUsersCourseAssignmentHistory )
			history_item = assignment_history.get(assignment_id)
			if history_item is None:
				continue # No submission for this assignment

			# Hmm, if they don't submit or submit in different orders,
			# numbers won't work. We need to canonicalize this to the assignment
			# order.
			for sub_num, sub_part in enumerate(history_item.Submission.parts):
				for q_num, q_part in enumerate(sub_part.questions):
					for qp_num, qp_part in enumerate(q_part.parts):
						if IQResponse.providedBy(qp_part):
							qp_part = qp_part.value

						if IQUploadedFile.providedBy(qp_part):
							full_filename = "%s/%s/%s/%s/%s" % (principal.id, sub_num, q_num, qp_num, qp_part.filename)
							info = ZipInfo(full_filename) # TODO: A date

							zipfile.writestr( info, qp_part.data )
		zipfile.close()
		buf.reset()

		self.request.response.body = buf.getvalue()
		self.request.response.content_disposition = b'attachment; filename="assignment.zip"'

		return self.request.response


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
			# Stop traversal here so our named view
			# gets to handle this
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

from .interfaces import IUsersCourseAssignmentHistoryItem
from nti.appserver.ugd_edit_views import UGDDeleteView
@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentHistoryItemDeleteView(UGDDeleteView):

	def _do_delete_object( self, theObject ):
		del theObject.__parent__[theObject.__name__]
		return theObject

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItemFeedback,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentHistoryItemFeedbackDeleteView(UGDDeleteView):

	def _do_delete_object( self, theObject ):
		del theObject.__parent__[theObject.__name__]
		return theObject


from nti.externalization.interfaces import LocatedExternalDict
from .interfaces import ICourseAssignmentCatalog
from .interfaces import ICourseAssessmentItemCatalog
from .interfaces import get_course_assignment_predicate_for_user

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='AssignmentsByOutlineNode') # See decorators
class AssignmentsByOutlineNodeDecorator(AbstractAuthenticatedView):
	"""
	For course instances (and things that can be adapted to them),
	there is a view at ``/.../AssignmentsByOutlineNode``. For
	authenticated users, it returns a map from NTIID to the assignments
	contained within that NTIID.

	At this time, nodes in the course outline
	do not have their own identity as NTIIDs; therefore, the NTIIDs
	returned from here are the NTIIDs of content pages that show up
	in the individual lessons; for maximum granularity, these are returned
	at the lowest level, so a client may need to walk \"up\" the tree
	to identify the corresponding level it wishes to display.
	"""

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		catalog = ICourseAssignmentCatalog(instance)

		uber_filter = get_course_assignment_predicate_for_user(self.remoteUser, instance)

		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		for asg in (x for x in catalog.iter_assignments() if uber_filter(x)):
			# The assignment's __parent__ is always the 'home'
			# content unit
			unit = asg.__parent__
			result.setdefault(unit.ntiid, []).append(asg)

		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='NonAssignmentAssessmentItemsByOutlineNode') # See decorators
class NonAssignmentsByOutlineNodeDecorator(AbstractAuthenticatedView):
	"""
	For course instances (and things that can be adapted to them),
	there is a view at ``/.../NonAssignmentAssessmentItemsByOutlineNode``. For
	authenticated users, it returns a map from NTIID to the assessment items
	contained within that NTIID.

	At this time, nodes in the course outline
	do not have their own identity as NTIIDs; therefore, the NTIIDs
	returned from here are the NTIIDs of content pages that show up
	in the individual lessons; for maximum granularity, these are returned
	at the lowest level, so a client may need to walk \"up\" the tree
	to identify the corresponding level it wishes to display.
	"""

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		catalog = ICourseAssessmentItemCatalog(instance)

		# Not only must we filter out assignments, we must filter out
		# the question sets that they refer to if they are not allowed
		# by the filter; we assume such sets are only used by the
		# assignment.
		# XXX FIXME not right. See also decorators.py
		# which does this for page info
		uber_filter = get_course_assignment_predicate_for_user(self.remoteUser, instance)

		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		qsids_to_strip = set()

		for item in catalog.iter_assessment_items():
			if IQAssignment.providedBy(item):
				if not uber_filter(item):
					for assignment_part in item.parts:
						question_set = assignment_part.question_set
						qsids_to_strip.add(question_set.ntiid)
						for question in question_set.questions:
							qsids_to_strip.add(question.ntiid)
			else:
				# The assignment's __parent__ is always the 'home'
				# content unit
				unit = item.__parent__
				result.setdefault(unit.ntiid, []).append(item)

		# Now remove the forbidden
		for items in result.values():
			for item in list(items):
				if item.ntiid in qsids_to_strip:
					items.remove(item)

		return result
