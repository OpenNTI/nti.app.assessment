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

from zope import component
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
from nti.contenttypes.courses.interfaces import	ICourseCatalogEntry

from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverFolder

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from .._submission import course_submission_report

from .._question_map import _add_assessment_items_from_new_content
from .._question_map import _remove_assessment_items_from_oldcontent

from ..interfaces import ICourseAssessmentItemCatalog
from ..interfaces import IUsersCourseAssignmentHistory
from ..interfaces import IUsersCourseAssignmentSavepoint

from ..common import get_course_assignments
from ..common import get_course_assignment_items

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
			 request_method='POST',
			 context=IDataserverFolder,
			 name='RemoveMatchedSavePoints')
class RemovedMatchedSavePointsView(	AbstractAuthenticatedView,
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
						self._delitemf(assignmentId, event=False)
						items = result.setdefault(principal.username, [])
						items.append(assignmentId)
		return result

def _parse_catalog_entry(params):
	ntiid = params.get('ntiid') or \
			params.get('entry') or \
			params.get('course')
	if not ntiid:
		return None
	
	context = find_object_with_ntiid(ntiid)
	result = ICourseCatalogEntry(context, None)
	if result is None:	
		try:
			catalog = component.getUtility(ICourseCatalog)
			result = catalog.getCatalogEntry(ntiid)
		except KeyError:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
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
		entry = _parse_catalog_entry(params)
		if entry is not None:
			entries = (entry,)
		else:
			entries = catalog.iterCatalogEntries()
			
		response = self.request.response	
		response.content_encoding = str('identity' )
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str( 'attachment; filename="report.csv"' )
		
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
			 request_method='GET',
			 context=IDataserverFolder,
			 name='CourseSubmissionReport')
class CourseSubmissionReportView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = _parse_catalog_entry(params)
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
		response.content_encoding = str('identity' )
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str( 'attachment; filename="report.csv"' )
		
		stream, _ = course_submission_report(context=context, 
							 	 		  	 question=question,
							 	 		 	 usernames=usernames,
								 		 	 assignment=assignment)
		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 request_method='GET',
			 context=IDataserverFolder,
			 name='CourseAssignments')
class CourseAssignmentsView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = _parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
		course = ICourseInstance(context)				
		
		do_filtering = params.get('filter') or 'true'
		do_filtering = do_filtering.lower() in ('true', 'T', '1')
		
		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for assignment in get_course_assignments(course=course, do_filtering=do_filtering):
			items[assignment.ntiid] = assignment
		result['Total'] = len(items)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 request_method='GET',
			 context=IDataserverFolder,
			 name='CourseAssignmentItems')
class CourseAssignmentItemsView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = _parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
		course = ICourseInstance(context)				
		
		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for item in get_course_assignment_items(course=course):
			items[item.ntiid] = item
		result['Count'] = result['Total'] = len(items)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 request_method='POST',
			 context=IDataserverFolder,
			 name='UnregisterAssessmentItems')
class UnregisterAssessmentItemsView(AbstractAuthenticatedView,
							   		ModeledContentUploadRequestUtilsMixin):
	
	def _do_call(self):
		values = CaseInsensitiveDict(self.readInput())
		ntiid = values.get('ntiid') or values.get('pacakge')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity("Invalid content package NTIID")
		
		package = find_object_with_ntiid(ntiid)
		if not IContentPackage.providedBy(package):
			raise hexc.HTTPUnprocessableEntity("Invalid content package")
		
		items = _remove_assessment_items_from_oldcontent(package)
		result = LocatedExternalDict()
		result[ITEMS] = sorted(items.keys())
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 request_method='POST',
			 context=IDataserverFolder,
			 name='RegisterAssessmentItems')
class RegisterAssessmentItemsView(AbstractAuthenticatedView,
						   		  ModeledContentUploadRequestUtilsMixin):
	
	def _do_call(self):
		values = CaseInsensitiveDict(self.readInput())
		ntiid = values.get('ntiid') or values.get('pacakge')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity("Invalid content package NTIID")
		
		package = find_object_with_ntiid(ntiid)
		if not IContentPackage.providedBy(package):
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
		return result
