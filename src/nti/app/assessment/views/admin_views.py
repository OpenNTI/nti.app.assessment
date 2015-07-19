#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
import six
from io import BytesIO

import zope.intid
from zope import component

from zope.catalog.interfaces import ICatalog

from zope.security.interfaces import IPrincipal

from pyramid.view import view_config
from pyramid.view import view_defaults
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.maps import CaseInsensitiveDict

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver.users import User
from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverFolder
from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.zope_catalog.catalog import ResultSet

from .._common_reports import course_submission_report

from .._question_map import _add_assessment_items_from_new_content
from .._question_map import _remove_assessment_items_from_oldcontent

from ..common import get_course_assignments
from ..common import get_course_assessment_items

from ..index import CATALOG_NAME as ASSESMENT_CATALOG_NAME

from ..interfaces import ICourseAssessmentItemCatalog
from ..interfaces import IUsersCourseAssignmentHistory
from ..interfaces import IUsersCourseAssignmentSavepoint

from . import parse_catalog_entry

ITEMS = StandardExternalFields.ITEMS

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   request_method='GET',
			   name='AllTasksOutline')
class AllTasksOutlineView(AbstractAuthenticatedView):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		catalog = ICourseAssessmentItemCatalog(instance)

		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		for item in catalog.iter_assessment_items():
			unit = item.__parent__
			result.setdefault(unit.ntiid, []).append(item)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 context=IDataserverFolder,
			 name='RemoveMatchedSavePoints')
class RemovedMatchedSavePointsView(AbstractAuthenticatedView,
							   		ModeledContentUploadRequestUtilsMixin):

	"""
	Remove savepoint for already submitted assignment(s)
	"""

	def _do_call(self):
		result = LocatedExternalDict()
		catalog = component.getUtility(ICourseCatalog)
		for entry in catalog.iterCatalogEntries():
			course = ICourseInstance(entry)
			enrollments = ICourseEnrollments(course)
			for record in enrollments.iter_enrollments():
				principal = record.Principal
				history = component.queryMultiAdapter((course, principal),
													  IUsersCourseAssignmentHistory)
				savepoint = component.queryMultiAdapter((course, principal),
														IUsersCourseAssignmentSavepoint)
				if not savepoint or not history:
					continue
				for assignmentId in history.keys():
					if assignmentId in savepoint:
						savepoint._delitemf(assignmentId, event=False)
						items = result.setdefault(principal.username, [])
						items.append(assignmentId)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 request_method='GET',
			 context=IDataserverFolder,
			 name='UnmatchedSavePoints')
class UnmatchedSavePointsView(AbstractAuthenticatedView):

	def __call__(self):
		catalog = component.getUtility(ICourseCatalog)
		params = CaseInsensitiveDict(self.request.params)
		entry = parse_catalog_entry(params)
		if entry is not None:
			entries = (entry,)
		else:
			entries = catalog.iterCatalogEntries()

		response = self.request.response
		response.content_encoding = str('identity')
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str('attachment; filename="report.csv"')

		stream = BytesIO()
		writer = csv.writer(stream)
		header = ['course', 'username', 'assignment']
		writer.writerow(header)

		for entry in entries:
			ntiid = entry.ntiid
			course = ICourseInstance(entry)
			enrollments = ICourseEnrollments(course)
			for record in enrollments.iter_enrollments():
				principal = record.Principal
				if IPrincipal(principal, None) is None:
					continue

				history = component.queryMultiAdapter((course, principal),
													  IUsersCourseAssignmentHistory)

				savepoint = component.queryMultiAdapter((course, principal),
														IUsersCourseAssignmentSavepoint)
				if not savepoint:
					continue

				for assignmentId in savepoint.keys():
					if assignmentId not in history or ():
						row_data = [ntiid, principal.username, assignmentId]
						writer.writerow(row_data)

		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 context=IDataserverFolder,
			 name='UnregisterAssessmentItems')
class UnregisterAssessmentItemsView(AbstractAuthenticatedView,
							   		ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		if self.request.body:
			values = read_body_as_external_object(self.request)
		else:
			values = self.request.params
		result = CaseInsensitiveDict(values)
		return result

	def _do_call(self):
		values = self.readInput()
		ntiid = values.get('ntiid') or values.get('pacakge')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity("Invalid content package NTIID")

		package = find_object_with_ntiid(ntiid)
		package = IContentPackage(package, None)
		if package is None:
			raise hexc.HTTPUnprocessableEntity("Invalid content package")

		items = _remove_assessment_items_from_oldcontent(package)
		result = LocatedExternalDict()
		result[ITEMS] = sorted(items.keys())
		result['Count'] = result['Total'] = len(items)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 context=IDataserverFolder,
			 name='RegisterAssessmentItems')
class RegisterAssessmentItemsView(AbstractAuthenticatedView,
						   		  ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		if self.request.body:
			values = read_body_as_external_object(self.request)
		else:
			values = self.request.params
		result = CaseInsensitiveDict(values)
		return result

	def _do_call(self):
		values = self.readInput()
		ntiid = values.get('ntiid') or values.get('pacakge')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity("Invalid content package NTIID")

		package = find_object_with_ntiid(ntiid)
		package = IContentPackage(package, None)
		if package is None:
			raise hexc.HTTPUnprocessableEntity("Invalid content package")

		items = ()
		result = LocatedExternalDict()
		key = package.does_sibling_entry_exist('assessment_index.json')
		if key is not None:
			items = _add_assessment_items_from_new_content(package, key)
			main_container = IQAssessmentItemContainer(package)
			main_container.lastModified = key.lastModified
			result.lastModified = key.lastModified
		result[ITEMS] = sorted(items)
		result['Count'] = result['Total'] = len(items)
		return result

@view_config(name="ReindexAssesmentItems")
@view_config(name="reindex_assesment_items")
@view_defaults(route_name='objects.generic.traversal',
			 	renderer='rest',
			 	permission=nauth.ACT_NTI_ADMIN,
			 	context=IDataserverFolder)
class ReindexAssesmentItemsView(AbstractAuthenticatedView,
						   		ModeledContentUploadRequestUtilsMixin):

	def _do_call(self):
		MIME_TYPES = ('application/vnd.nextthought.assessment.userscourseassignmenthistoryitem',
					  'application/vnd.nextthought.assessment.userscourseinquiryitem')

		total = 0
		errors = 0
		intids = component.getUtility(zope.intid.IIntIds)
		metadata_catalog = component.getUtility(ICatalog, METADATA_CATALOG_NAME)
		assesment_catalog = component.getUtility(ICatalog, ASSESMENT_CATALOG_NAME)

		item_intids = metadata_catalog['mimeType'].apply({'any_of': MIME_TYPES})
		results = ResultSet(item_intids, intids, True)
		for uid, obj in results.iter_pairs():
			try:
				assesment_catalog.force_index_doc(uid, obj)
				total += 1
			except Exception:
				errors += 1
				logger.debug("Cannot index object with id %s", uid)

		result = LocatedExternalDict()
		result['Total'] = total
		result['Errors'] = errors
		return result

# course views

from nti.app.externalization.internalization import read_body_as_external_object

from nti.app.products.courseware.views import CourseAdminPathAdapter

from .._assessment import move_user_assignment_from_course_to_course

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_config(name='CourseSubmissionReport')
@view_defaults(route_name='objects.generic.traversal',
				renderer='rest',
				permission=nauth.ACT_NTI_ADMIN,
				request_method='GET')
class CourseSubmissionReportView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")

		usernames = params.get('usernames') or params.get('username')
		if isinstance(usernames, six.string_types):
			usernames = usernames.split(',')
		usernames = {x.lower() for x in usernames or ()}

		assignment = params.get('assignmentId') or params.get('assignment')
		if assignment and component.queryUtility(IQAssignment, name=assignment) is None:
			raise hexc.HTTPUnprocessableEntity("Invalid assignment")

		question = params.get('questionId') or params.get('question')
		if question and component.queryUtility(IQuestion, name=question) is None:
			raise hexc.HTTPUnprocessableEntity("Invalid question")

		response = self.request.response
		response.content_encoding = str('identity')
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str('attachment; filename="report.csv"')

		stream, _ = course_submission_report(context=context,
							 	 		  	 question=question,
							 	 		 	 usernames=usernames,
								 		 	 assignment=assignment)
		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
			 	renderer='rest',
			 	permission=nauth.ACT_NTI_ADMIN,
			 	request_method='GET',
			 	name='CourseAssignments')
class CourseAssignmentsView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
		course = ICourseInstance(context)

		do_filtering = params.get('filter') or 'true'
		do_filtering = do_filtering.lower() in ('true', 'T', '1')

		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for assignment in get_course_assignments(course=course,
												 do_filtering=do_filtering):
			items[assignment.ntiid] = assignment
		result['Total'] = len(items)
		return result

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
				renderer='rest',
				permission=nauth.ACT_NTI_ADMIN,
				request_method='GET',
				name='CourseAssessmentItems')
class CourseAssessmentItemsView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
		course = ICourseInstance(context)

		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for item in get_course_assessment_items(course=course):
			items[item.ntiid] = item
		result['Count'] = result['Total'] = len(items)
		return result

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_config(name="MoveUserAssignments")
@view_config(name="MoveUserAssignmentsView")
@view_defaults(route_name='objects.generic.traversal',
				renderer='rest',
				permission=nauth.ACT_NTI_ADMIN,
				name='MoveUserAssignmentsView')
class MoveUserAssignmentsView(AbstractAuthenticatedView,
							  ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		if self.request.body:
			values = read_body_as_external_object(self.request)
		else:
			values = self.request.params
		result = CaseInsensitiveDict(values)
		return result

	def __call__(self):
		values = self.readInput()
		source = parse_catalog_entry(values, names=("source", "origin"))
		target = parse_catalog_entry(values, names=("target", "dest"))
		if source is None:
			raise hexc.HTTPUnprocessableEntity("Invalid source NTIID")
		if target is None:
			raise hexc.HTTPUnprocessableEntity("Invalid target NTIID")
		if source == target:
			raise hexc.HTTPUnprocessableEntity("Source and Target courses are the same")

		source = ICourseInstance(source)
		target = ICourseInstance(target)

		usernames = values.get('usernames') or values.get('username')
		if usernames:
			usernames = usernames.split(',')
		else:
			usernames = tuple(ICourseEnrollments(source).iter_principals())

		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for username in usernames:
			user = User.get_user(username)
			if user is None:
				logger.info("User %s does not exists", username)
			moved = move_user_assignment_from_course_to_course(user, source, target)
			items[username] = sorted(moved)
		result['Count'] = result['Total'] = len(items)
		return result
