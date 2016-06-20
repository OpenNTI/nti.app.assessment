#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment submission/history

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from numbers import Number
from urllib import unquote
from datetime import datetime
from cStringIO import StringIO

from zipfile import ZipInfo
from zipfile import ZipFile

from zope import component

from zope.container.traversal import ContainerTraversable

from zope.location.interfaces import LocationError

from pyramid import httpexceptions as hexc

from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment._submission import get_source
from nti.app.assessment._submission import check_upload_files
from nti.app.assessment._submission import read_multipart_sources

from nti.app.assessment.common import get_course_from_assignment

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.app.assessment.utils import replace_username
from nti.app.assessment.utils import assignment_download_precondition

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.internalization import read_input_data

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQUploadedFile
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser

from nti.dataserver.users import User

from nti.dataserver.users.interfaces import IUserProfile

from nti.ntiids.ntiids import find_object_with_ntiid

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 # permission=nauth.ACT_CREATE, # see below
			 request_method='POST')
class AssignmentSubmissionPostView(AbstractAuthenticatedView,
								   ModeledContentUploadRequestUtilsMixin):
	"""
	Students can POST to the assignment to create their submission.
	"""

	# If the user submits a badly formed submission, we can get
	# this, especially if we try to autograde. (That particular case
	# is now handled, but still.)
	_EXTRA_INPUT_ERRORS = ModeledContentUploadRequestUtilsMixin._EXTRA_INPUT_ERRORS + \
						  (AttributeError,)

	# XXX: We would like to express access control via
	# an ACL or the zope security role map.
	# In the past, this more-or-less worked because there was
	# one piece of content defining one course containing assignments only
	# used by that course, and moreover, that course knew exactly about its
	# permissioning and was intimately tied to a global community that enrolled
	# users were put in. Thus, the .nti_acl file that defined access to the course content
	# also served for the assignment.
	# Now, however, we're in the situation where none of that holds: courses
	# are separate from content, and define their own permissioning. But assignments are
	# still defined from a piece of content and would inherit its permissions if we let it.

	# Therefore, we simply do not specify a permission for this view, and instead
	# do an enrollment check.

	content_predicate = IQAssignmentSubmission.providedBy

	def _validate_submission(self):
		creator = self.remoteUser
		course = component.queryMultiAdapter((self.context, creator),
											  ICourseInstance)
		if course is None:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

	def _do_call(self):
		creator = self.remoteUser
		self._validate_submission()

		if not self.request.POST:
			submission = self.readCreateUpdateContentObject(creator)
			check_upload_files(submission)
		else:
			extValue = get_source(self.request, 'json', 'input', 'submission')
			if not extValue:
				raise hexc.HTTPUnprocessableEntity("No submission source was specified")
			extValue = extValue.read()
			extValue = read_input_data(extValue, self.request)
			submission = self.readCreateUpdateContentObject(creator, externalValue=extValue)
			submission = read_multipart_sources(submission, self.request)

		# Re-use the same code for putting to a user
		result = component.getMultiAdapter((self.request, submission), IExceptionResponse)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 name=ASSESSMENT_PRACTICE_SUBMISSION,
			 request_method='POST')
class AssignmentPracticeSubmissionPostView(AssignmentSubmissionPostView):
	"""
	A practice assignment submission view that will submit/grade results
	but not persist.
	"""

	def _validate_submission(self):
		pass

	def _do_call(self):
		try:
			result = super(AssignmentPracticeSubmissionPostView, self)._do_call()
			return result
		finally:
			self.request.environ['nti.commit_veto'] = 'abort'

@view_config(route_name="objects.generic.traversal",
			 context=IQAssignment,
			 renderer='rest',
			 # permission=ACT_DOWNLOAD_GRADES, # handled manually because it's on the course, not the context
			 request_method='GET',
			 name='BulkFilePartDownload')
class AssignmentSubmissionBulkFileDownloadView(AbstractAuthenticatedView):
	"""
	A view that returns a ZIP file containing all
	the files submitted by any student in the course forz
	any file part in the given assignment.

	The ZIP has the following structure::

	<student-username>/
		<part-num>/
			<question-num>/
				<submitted-file-name>

	For the convenience of people that don't understand directories
	and how to work with them, this structure is flattened
	using dashes.

	.. note:: An easy extension to this would be to accept
		a query param giving a list of usernames to include.

	.. note:: The current implementation does not stream;
		the entire ZIP is buffered (potentially in memory) before being
		transmitted. Streaming while building a ZIP is somewhat
		complicated in the ZODB/WSGI combination. It may be possible
		to do something with app_iter and stream in \"chunks\".
	"""

	def _get_course(self, context):
		result = None
		course_id = self.request.params.get('course')
		course_id = unquote(course_id) if course_id else None
		if course_id:
			result = find_object_with_ntiid(course_id)
			result = ICourseInstance(result, None)
		if result is None:
			# Ok, pick the first course we find.
			result = get_course_from_assignment(context, self.remoteUser, exc=True)
		return result

	def _string(self, val, sub=''):
		if val:
			val = val.replace( ' ', sub )
		return val

	def _get_course_name(self, course):
		entry = ICourseCatalogEntry( course, None )
		if entry is not None:
			base_name = entry.ProviderUniqueID
			base_name = self._string( base_name )
		if not base_name:
			base_name = course.__name__
		return base_name

	def _get_assignment_name(self):
		context = self.context
		result = getattr( context, 'title', context.__name__ )
		result = self._string( result, '_' )
		return result or 'assignment'

	def _get_filename(self, course):
		base_name = self._get_course_name( course )
		assignment_name = self._get_assignment_name()
		suffix = '.zip'
		result = '%s_%s%s' % (base_name, assignment_name, suffix)
		return result

	@classmethod
	def _precondition(cls, context, request, remoteUser):
		return assignment_download_precondition(context, request, remoteUser)

	def _get_username_filename_part(self, principal):
		user = User.get_entity( principal.id )
		profile = IUserProfile( user )
		realname = profile.realname or ''
		realname = realname.replace( ' ', '_' )
		username = replace_username( user.username )
		result = username
		if realname:
			result = '%s-%s' % (username, realname)
		return result

	def __call__(self):
		context = self.request.context
		request = self.request

		if not self._precondition(context, request, self.remoteUser):
			raise hexc.HTTPForbidden()

		# We're assuming we'll find some submitted files.
		# What should we do if we don't?
		assignment_id = context.__name__

		course = self._get_course(context)
		enrollments = ICourseEnrollments(course)

		buf = StringIO()
		zipfile = ZipFile(buf, 'w')
		for record in enrollments.iter_enrollments():
			principal = IUser(record)
			assignment_history = component.getMultiAdapter((course, principal),
															IUsersCourseAssignmentHistory)
			history_item = assignment_history.get(assignment_id)
			if history_item is None:
				continue  # No submission for this assignment

			# Hmm, if they don't submit or submit in different orders,
			# numbers won't work. We need to canonicalize this to the assignment order.
			for sub_num, sub_part in enumerate(history_item.Submission.parts):
				for q_num, q_part in enumerate(sub_part.questions):
					for qp_num, qp_part in enumerate(q_part.parts):
						if IQResponse.providedBy(qp_part):
							qp_part = qp_part.value

						if IQUploadedFile.providedBy(qp_part):

							user_filename_part = self._get_username_filename_part( principal )
							full_filename = "%s-%s-%s-%s-%s" % (user_filename_part, sub_num, q_num,
																qp_num, qp_part.filename)

							date_time = datetime.utcfromtimestamp(qp_part.lastModified)
							info = ZipInfo(full_filename, date_time=date_time.timetuple())

							zipfile.writestr(info, qp_part.data)
		zipfile.close()
		buf.reset()

		self.request.response.body = buf.getvalue()
		filename = self._get_filename( course )
		self.request.response.content_disposition = 'attachment; filename="%s"' % filename

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

@component.adapter(IUsersCourseAssignmentHistory, IRequest)
class AssignmentHistoryRequestTraversable(ContainerTraversable):

	def __init__(self, context, request):
		ContainerTraversable.__init__(self, context)

	def traverse(self, name, further_path):
		if name == 'lastViewed':
			# Stop traversal here so our named view
			# gets to handle this
			raise LocationError(self._container, name)
		return ContainerTraversable.traverse(self, name, further_path)

@view_config(route_name="objects.generic.traversal",
			 renderer='rest',
			 context=IUsersCourseAssignmentHistory,
			 # We handle permissioning manually, not sure
			 # what context this is going to be in
			 # permission=nauth.ACT_UPDATE,
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
		if self.request.context.owner != self.remoteUser:
			raise hexc.HTTPForbidden("Only the student can set lastViewed")
		ext_input = self.readInput()
		history = self.request.context
		self.request.context.lastViewed = ext_input
		return history

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentHistoryItemDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject
