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
import urllib
from io import BytesIO

from zope import component

from pyramid.view import view_config
from pyramid.view import view_defaults
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverFolder

from nti.externalization.interfaces import LocatedExternalDict

from nti.ntiids.ntiids import TYPE_OID
from nti.ntiids.ntiids import is_ntiid_of_type
from nti.ntiids.ntiids import find_object_with_ntiid

from nti.utils.maps import CaseInsensitiveDict

from .._submission import course_submission_report

from ..interfaces import ICourseAssessmentItemCatalog
from ..interfaces import IUsersCourseAssignmentHistory
from ..interfaces import IUsersCourseAssignmentSavepoint

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_MODERATE,
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
			 permission=nauth.ACT_MODERATE,
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

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_MODERATE,
			 request_method='GET',
			 context=IDataserverFolder,
			 name='UnmatchedSavePoints')
class UnmatchedSavePointsView(AbstractAuthenticatedView):

	def __call__(self):
		catalog = component.getUtility(ICourseCatalog)
		params = CaseInsensitiveDict(self.request.params)
		ntiid = params.get('ntiid') or \
				params.get('entry') or \
				params.get('course')
		if ntiid:
			try:
				ntiid = urllib.unquote(ntiid)
				entries = (catalog.getCatalogEntry(ntiid),)
			except KeyError:
				raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
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
				history = component.queryMultiAdapter((course, principal), 
													  IUsersCourseAssignmentHistory)
				savepoint = component.queryMultiAdapter((course, principal), 
													    IUsersCourseAssignmentSavepoint)
	
				for assignmentId in savepoint.keys():
					if assignmentId not in history:
						row_data = [ntiid, principal.username, assignmentId]
						writer.writerow(row_data)
			
		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_MODERATE,
			 request_method='GET',
			 context=IDataserverFolder,
			 name='CourseSubmissionReport')
class CourseSubmissionReportView(AbstractAuthenticatedView):

	def __call__(self):
		catalog = component.getUtility(ICourseCatalog)
		params = CaseInsensitiveDict(self.request.params)
		ntiid = params.get('ntiid') or \
				params.get('entry') or \
				params.get('course')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity("Must specify a course/entry NTIID")
		
		if not is_ntiid_of_type(ntiid, TYPE_OID):
			try:
				ntiid = urllib.unquote(ntiid)
				context = catalog.getCatalogEntry(ntiid)
			except KeyError:
				raise hexc.HTTPUnprocessableEntity("Invalid entry NTIID")
		else:
			obj = find_object_with_ntiid(ntiid)
			context = ICourseInstance(obj, None)
			if context is None:
				raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
		
		usernames = params.get('usernames') or \
					params.get('username')
		if isinstance(usernames, six.string_types):
			usernames = usernames.split(',')
		usernames = {x.lower() for x in usernames or ()}
		
		assignment = params.get('assignmentId') or \
					 params.get('assignment')
		if assignment and component.queryUtility(IQAssignment, name=assignment) is None:
			raise hexc.HTTPUnprocessableEntity("Invalid assignment")

		question = params.get('questionId') or \
				   params.get('question')
		if question and component.queryUtility(IQuestion, name=question) is None:
			raise hexc.HTTPUnprocessableEntity("Invalid question")
		
		response = self.request.response	
		response.content_encoding = str('identity' )
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str( 'attachment; filename="report.csv"' )
		
		stream = course_submission_report(context=context, 
							 	 		  question=question,
							 	 		  usernames=usernames,
								 		  assignment=assignment)
		
		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response
