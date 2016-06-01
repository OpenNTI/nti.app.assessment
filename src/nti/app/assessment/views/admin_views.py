#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
from io import BytesIO

from zope import component

from zope.component.hooks import site as current_site

from zope.security.interfaces import IPrincipal

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment import MessageFactory as _

from nti.app.assessment._integrity_check import check_assessment_integrity

from nti.app.assessment._question_map import _add_assessment_items_from_new_content
from nti.app.assessment._question_map import _remove_assessment_items_from_oldcontent

from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import get_course_from_inquiry

from nti.app.assessment.interfaces import IUsersCourseInquiry
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint

from nti.app.assessment.views import parse_catalog_entry

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.internalization import read_body_as_external_object
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.maps import CaseInsensitiveDict

from nti.common.string import is_true

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserverFolder

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.hostpolicy import get_host_site

ITEMS = StandardExternalFields.ITEMS

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 context=IDataserverFolder,
			 request_method='POST',
			 name='CheckAssessmentIntegrity')
class CheckAssessmentIntegrityView(AbstractAuthenticatedView,
							   	   ModeledContentUploadRequestUtilsMixin):
	
	def readInput(self, value=None):
		if self.request.body:
			result = CaseInsensitiveDict(read_body_as_external_object(self.request))
		else:
			result = CaseInsensitiveDict()
		return result

	def _do_call(self):
		values = self.readInput()
		unparented = is_true(values.get('unparented'))
		integrity = check_assessment_integrity(unparented)
		duplicates, removed, reindexed, fixed_lineage, adjusted = integrity
		result = LocatedExternalDict()
		result['Duplicates'] = duplicates
		result['Removed'] = sorted(removed)
		result['Reindexed'] = sorted(reindexed)
		result['FixedLineage'] = sorted(fixed_lineage)
		result['AdjustedContainer'] = sorted(adjusted)
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
		items = result[ITEMS] = {}
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
						assignments = items.setdefault(principal.username, [])
						assignments.append(assignmentId)
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
			raise hexc.HTTPUnprocessableEntity(_("Invalid content package NTIID."))

		force =  is_true(values.get('force'))
		package = find_object_with_ntiid(ntiid)
		package = IContentPackage(package, None)
		if package is None:
			raise hexc.HTTPUnprocessableEntity(_("Invalid content package."))

		name = get_resource_site_name(package)
		site = get_host_site(name)
		with current_site(site):
			items = _remove_assessment_items_from_oldcontent(package, force=force)
		result = LocatedExternalDict()
		result[ITEMS] = sorted(items.keys())
		result['ItemCount'] = result['Total'] = len(items)
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
			raise hexc.HTTPUnprocessableEntity(_("Invalid content package NTIID."))

		package = find_object_with_ntiid(ntiid)
		package = IContentPackage(package, None)
		if package is None:
			raise hexc.HTTPUnprocessableEntity(_("Invalid content package."))

		items = ()
		result = LocatedExternalDict()
		key = package.does_sibling_entry_exist('assessment_index.json')
		if key is not None:
			name = get_resource_site_name(package)
			site = get_host_site(name)
			with current_site(site):
				items = _add_assessment_items_from_new_content(package, key)
				main_container = IQAssessmentItemContainer(package)
				main_container.lastModified = key.lastModified
				result.lastModified = key.lastModified
		result[ITEMS] = sorted(items)
		result['ItemCount'] = result['Total'] = len(items)
		return result

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 context=IDataserverFolder,
			 name='ResetInquiry')
class ResetInquiryView(AbstractAuthenticatedView,
					   ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		values = super(ResetInquiryView, self).readInput(value=value)
		result = CaseInsensitiveDict(values)
		return result

	def _do_call(self):
		creator = None
		values = self.readInput()

		ntiid = values.get('ntiid') or values.get('inquiry')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity(_("Must provide an inquiry ntiid."))
		inquiry = component.getUtility(IQInquiry, name=ntiid)
		if inquiry is None:
			raise hexc.HTTPUnprocessableEntity(_("Must provide a valid inquiry."))

		course = values.get('entry') or values.get('course')
		if course:
			course = find_object_with_ntiid(course)
			course = ICourseInstance(course, None)
			if course is None:
				raise hexc.HTTPUnprocessableEntity(_("Must provide a valid course ntiid."))

		# check for a user (inquiry taker)
		username = values.get('username') or values.get('user') or values.get('taker')
		
		# if a course was provided, but no taker, delete all entries
		if course is not None and not username:
			inquiries = IUsersCourseInquiries(course)
			for inquiry in inquiries.values():
				if ntiid in inquiry:
					del inquiry[ntiid]
			return hexc.HTTPNoContent()
		
		if not username:
			raise hexc.HTTPUnprocessableEntity(_("Must provide a username."))
			creator = User.get_user(username)
		if creator is None or not IUser.providedBy(creator):
			raise hexc.HTTPUnprocessableEntity(_("Must provide a valid user."))

		course = get_course_from_inquiry(inquiry, creator) if course is None else course
		if course is None:
			raise hexc.HTTPForbidden(_("Must be enrolled in a course."))

		course_inquiry = component.queryMultiAdapter((course, creator),
													 IUsersCourseInquiry)
		if course_inquiry and ntiid in course_inquiry:
			del course_inquiry[ntiid]
			return hexc.HTTPNoContent()
		else:
			raise hexc.HTTPUnprocessableEntity(_("User has not taken inquiry."))
