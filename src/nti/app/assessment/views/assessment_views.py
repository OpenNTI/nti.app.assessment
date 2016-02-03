#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from cStringIO import StringIO
from datetime import datetime
from numbers import Number
from urllib import unquote

from zipfile import ZipInfo
from zipfile import ZipFile

from zope import component

from zope.location.interfaces import LocationError

from pyramid import httpexceptions as hexc

from pyramid.interfaces import IRequest
from pyramid.interfaces import IExceptionResponse

from pyramid.view import view_config
from pyramid.view import view_defaults
from zope.container.traversal import ContainerTraversable

from nti.app.assessment.common import get_course_from_assignment

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedbackContainer

from nti.app.assessment._submission import get_source
from nti.app.assessment._submission import check_upload_files
from nti.app.assessment._submission import read_multipart_sources

from nti.app.assessment.utils import copy_assignment
from nti.app.assessment.utils import replace_username

from nti.app.assessment.views import assignment_download_precondition

from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentlibrary.utils import PAGE_INFO_MT
from nti.app.contentlibrary.utils import PAGE_INFO_MT_JSON
from nti.app.contentlibrary.utils import find_page_info_view_helper

from nti.app.externalization.internalization import read_input_data

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQUploadedFile
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.common.property import Lazy

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import ICourseOutlineContentNode
from nti.contenttypes.courses.interfaces import ICourseAssessmentItemCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.contenttypes.presentation.interfaces import INTIAssignmentRef
from nti.contenttypes.presentation.interfaces import INTIQuestionSetRef
from nti.contenttypes.presentation.interfaces import INTILessonOverview

from nti.dataserver.interfaces import IUser
from nti.dataserver import authorization as nauth

from nti.dataserver.users.interfaces import IUserProfile

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.oids import to_external_oid

from nti.ntiids.ntiids import find_object_with_ntiid

ITEMS = StandardExternalFields.ITEMS

# In pyramid 1.4, there is some minor wonkiness with the accept= request predicate.
# Your view can get called even if no Accept header is present if all the defined
# views include a non-matching accept predicate. Still, this is much better than
# the behaviour under 1.3.

_read_view_defaults = dict(route_name='objects.generic.traversal',
							renderer='rest',
							permission=nauth.ACT_READ,
							request_method='GET')
_question_view = dict(context=IQuestion)
_question_view.update(_read_view_defaults)

_question_set_view = dict(context=IQuestionSet)
_question_set_view.update(_read_view_defaults)

_assignment_view = dict(context=IQAssignment)
_assignment_view.update(_read_view_defaults)

_inquiry_view = dict(context=IQInquiry)
_inquiry_view.update(_read_view_defaults)

@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_assignment_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_inquiry_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_inquiry_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_assignment_view)
def pageinfo_from_question_view(request):
	assert request.accept
	# questions are now generally held within their containing IContentUnit,
	# but some old tests don't parent them correctly, using strings
	content_unit_or_ntiid = request.context.__parent__
	return find_page_info_view_helper(request, content_unit_or_ntiid)

@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_question_view)
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_question_set_view)
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_assignment_view)
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_inquiry_view)
def get_question_view_link(request):
	# Not supported.
	return hexc.HTTPBadRequest()

@view_config(accept=str(''),  # explicit empty accept, else we get a ConfigurationConflict
			 ** _question_view)  # and/or no-Accept header goes to the wrong place
@view_config(**_question_view)
@view_config(accept=str(''),
			 **_question_set_view)
@view_config(**_question_set_view)
@view_config(accept=str(''),
			 **_assignment_view)
@view_config(**_assignment_view)
@view_config(accept=str(''),
			 **_inquiry_view)
@view_config(**_inquiry_view)
def get_question_view(request):
	return request.context

del _inquiry_view
del _question_view
del _assignment_view
del _read_view_defaults

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

	def _do_call(self):
		creator = self.remoteUser
		course = component.queryMultiAdapter((self.context, creator),
											  ICourseInstance)
		if course is None:
			raise hexc.HTTPForbidden("Must be enrolled in a course.")

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
		# TODO: Shouldn't this be the external NTIID?
		# This is what ugd_edit_views does though
		self.request.response.location = \
				self.request.resource_url(creator,
										  'Objects',
										  to_external_oid(feedback))
		return feedback

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItem,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentHistoryItemDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject

@view_config(route_name="objects.generic.traversal",
			 context=IUsersCourseAssignmentHistoryItemFeedback,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class AssignmentHistoryItemFeedbackDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		del theObject.__parent__[theObject.__name__]
		return theObject

class AssignmentsByOutlineNodeMixin(AbstractAuthenticatedView):

	_LEGACY_UAS = (
		"NTIFoundation DataLoader NextThought/1.0",
		"NTIFoundation DataLoader NextThought/1.1.",
		"NTIFoundation DataLoader NextThought/1.2.",
		"NTIFoundation DataLoader NextThought/1.3.",
		"NTIFoundation DataLoader NextThought/1.4.0"
	)

	@Lazy
	def is_ipad_legacy(self):
		result = False
		ua = self.request.environ.get('HTTP_USER_AGENT', '')
		if ua:
			for bua in self._LEGACY_UAS:
				if ua.startswith(bua):
					result = True
					break
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='AssignmentsByOutlineNode')  # See decorators
class AssignmentsByOutlineNodeDecorator(AssignmentsByOutlineNodeMixin):
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

	@Lazy
	def is_course_instructor(self):
		return is_course_instructor_or_editor(self.context, self.remoteUser)

	def _do_outline(self, instance, items, outline):
		# reverse question set map
		# this is done in case question set refs
		# appear in a lesson overview
		reverse_qset = {}
		for assgs in items.values():
			for asg in assgs:
				for part in asg.parts:
					reverse_qset[part.question_set.ntiid] = asg.ntiid

		def _recur(node):
			if ICourseOutlineContentNode.providedBy(node) and node.ContentNTIID:
				key = node.ContentNTIID
				assgs = items.get(key)
				if assgs:
					outline[key] = [x.ntiid for x in assgs]
				try:
					name = node.LessonOverviewNTIID
					lesson = component.queryUtility(INTILessonOverview, name=name or u'')
					for group in lesson or ():
						for item in group:
							if INTIAssignmentRef.providedBy(item):
								outline.setdefault(key, [])
								outline[key].append(item.target or item.ntiid)
							elif INTIQuestionSetRef.providedBy(item):
								ntiid = reverse_qset.get(item.target)
								if ntiid:
									outline.setdefault(key, [])
									outline[key].append(item.target or item.ntiid)
				except AttributeError:
					pass
			for child in node.values():
				_recur(child)
		_recur(instance.Outline)
		return outline

	def _do_catalog(self, instance, result):
		catalog = ICourseAssignmentCatalog(instance)
		uber_filter = get_course_assessment_predicate_for_user(self.remoteUser, instance)
		for asg in (x for x in catalog.iter_assignments() if uber_filter(x)):
			# The assignment's __parent__ is always the 'home' content unit
			parent = asg.__parent__
			if parent is not None:
				if not self.is_ipad_legacy and self.is_course_instructor:
					asg = copy_assignment(asg, True)
				if ICourseInstance.providedBy(parent):
					parent = ICourseCatalogEntry(parent)
				result.setdefault(parent.ntiid, []).append(asg)
			else:
				logger.error("%s is an assignment without parent unit", asg.ntiid)
		return result

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		instance = ICourseInstance(self.request.context)
		if self.is_ipad_legacy:
			self._do_catalog(instance, result)
		else:
			items = result[ITEMS] = {}
			outline = result['Outline'] = {}
			self._do_catalog(instance, items)
			self._do_outline(instance, items, outline)
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='NonAssignmentAssessmentItemsByOutlineNode')  # See decorators
class NonAssignmentsByOutlineNodeDecorator(AssignmentsByOutlineNodeMixin):
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

	@Lazy
	def is_course_instructor(self):
		return is_course_instructor_or_editor(self.context, self.remoteUser)

	def _do_catalog(self, instance, result):
		# Not only must we filter out assignments, we must filter out
		# the question sets that they refer to if they are not allowed
		# by the filter; we assume such sets are only used by the
		# assignment.

		qsids_to_strip = set()
		catalog = ICourseAssessmentItemCatalog(instance)
		for item in catalog.iter_assessment_items():
			if IQAssignment.providedBy(item):
				for assignment_part in item.parts or ():
					question_set = assignment_part.question_set
					qsids_to_strip.add(question_set.ntiid)
					qsids_to_strip.update([q.ntiid for q in question_set.questions])
			elif IQSurvey.providedBy(item):
				qsids_to_strip.update([p.ntiid for p in item.questions or ()])
			else:
				# The item's __parent__ is always the 'home' content unit
				unit = item.__parent__
				if unit is not None:
					result.setdefault(unit.ntiid, {})[item.ntiid] = item
				else:
					logger.error("%s is an item without parent unit", item.ntiid)

		# Now remove the forbidden
		for unit_ntiid, items in list(result.items()): # mutating
			for ntiid in list(items.keys()):  # mutating
				if ntiid in qsids_to_strip:
					del items[ntiid]
			result[unit_ntiid] = list(items.values())

		return result

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		instance = ICourseInstance(self.request.context)
		if self.is_ipad_legacy:
			self._do_catalog(instance, result)
		else:
			items = result[ITEMS] = {}
			self._do_catalog(instance, items)
		return result

@view_config(route_name='objects.generic.traversal',
			 context=IQAssignment,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class AssignmentPutView(AssessmentPutView):

	def validate(self, contentObject, externalValue, courses=()):
		parts = externalValue.get('parts')
		if parts: # don't allow change on its parts
			raise hexc.HTTPForbidden(_("Cannot change the definition of an assignment"))
