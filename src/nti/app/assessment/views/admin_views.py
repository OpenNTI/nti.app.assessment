#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
import time
from io import BytesIO
from functools import partial

from zope import component

from zope.catalog.interfaces import ICatalog

from zope.intid import IIntIds

from zope.security.interfaces import IPrincipal
from zope.security.management import endInteraction
from zope.security.management import restoreInteraction

from zope.traversing.interfaces import IEtcNamespace

from pyramid.view import view_config
from pyramid.view import view_defaults
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.internalization import read_body_as_external_object
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import ASSESSMENT_INTERFACES

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.string import TRUE_VALUES
from nti.common.maps import CaseInsensitiveDict

from nti.contentlibrary.indexed_data import get_registry
from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssessmentItemCatalog

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserverFolder

from nti.dataserver.metadata_index import CATALOG_NAME as METADATA_CATALOG_NAME

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.utils import unregisterUtility
from nti.site.site import get_component_hierarchy_names

from nti.zope_catalog.catalog import ResultSet

from .._question_map import _add_assessment_items_from_new_content
from .._question_map import _remove_assessment_items_from_oldcontent

from ..common import get_course_inquiries
from ..common import get_course_assignments
from ..common import get_course_from_inquiry

from ..index import CATALOG_NAME as ASSESMENT_CATALOG_NAME

from ..interfaces import IUsersCourseInquiry
from ..interfaces import IUsersCourseInquiries
from ..interfaces import IUsersCourseAssignmentHistory
from ..interfaces import IUsersCourseAssignmentSavepoint

from . import parse_catalog_entry

ITEMS = StandardExternalFields.ITEMS

def is_true(value):
	return value and str(value).lower() in TRUE_VALUES

class CourseViewMixin(AbstractAuthenticatedView):

	def _do_call(self, func):
		count = 0
		result = LocatedExternalDict()
		items  = result[ITEMS] = {}
		params = CaseInsensitiveDict(self.request.params)
		outline = is_true(params.get('byOutline') or params.get('outline'))
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context
		for item in func():
			count += 1
			if not outline:
				items[item.ntiid] = item
			else:
				unit = item.__parent__
				ntiid = unit.ntiid if unit is not None else 'unparented'
				items.setdefault(ntiid, []).append(item)
		result['Total'] = result['ItemCount'] = count
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   request_method='GET',
			   name='Assessments')
class CourseAssessmentCatalogView(CourseViewMixin):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		catalog = ICourseAssessmentItemCatalog(instance)
		return self._do_call(catalog.iter_assessment_items)

@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   request_method='GET',
			   name='Assignments')
class CourseAssignmentsView(CourseViewMixin):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		func = partial(get_course_assignments, instance, do_filtering=False)
		return self._do_call(func)

@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   request_method='GET',
			   name='Inquiries')
class CourseInquiriesView(CourseViewMixin):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		func = partial(get_course_inquiries, instance, do_filtering=False)
		return self._do_call(func)

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

@view_config(context=IDataserverFolder)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   name='RemoveInaccessibleAssessment')
class RemoveInaccessibleAssessmentView(AbstractAuthenticatedView,
							  	   	   ModeledContentUploadRequestUtilsMixin):

	def _unregister(self, sites_names, provided, name):
		result = False
		hostsites = component.getUtility(IEtcNamespace, name='hostsites')
		for site_name in list(sites_names).reverse():
			try:
				folder = hostsites[site_name]
				registry = folder.getSiteManager()
				result = unregisterUtility(registry, 
										   provided=provided, 
										   name=name) or result
			except KeyError:
				pass
		return result

	def _assessments(self, registry):
		for iface in ASSESSMENT_INTERFACES:
			for ntiid, assg in list(registry.getUtilitiesFor(iface)):
				yield ntiid, assg

	def _do_call(self, result):
		registry = get_registry()
		catalog = get_library_catalog()
		sites = get_component_hierarchy_names()
		intids = component.getUtility(IIntIds)

		registered = 0
		items = result[ITEMS] = []
		references = catalog.get_references(sites=sites,
										 	provided=ASSESSMENT_INTERFACES)

		for ntiid, assg in self._assessments(registry):
			uid = intids.queryId(assg)
			provided = iface_of_assessment(assg)
			if uid is None:
				items.append(repr((provided.__name__, ntiid)))
				self._unregister(sites, provided=provided, name=ntiid)
			elif uid not in references:
				items.append(repr((provided.__name__, ntiid, uid)))
				self._unregister(sites, provided=provided, name=ntiid)
				intids.unregister(assg)
			registered += 1

		result['TotalRemoved'] = len(items)
		result['TotalRegisteredAssessment'] = registered
		result['TotalCatalogedAssessment'] = len(references)
		return result

	def __call__(self):
		now = time.time()
		result = LocatedExternalDict()
		endInteraction()
		try:
			self._do_call(result)
		finally:
			restoreInteraction()
			result['TimeElapsed'] = time.time() - now
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
		intids = component.getUtility(IIntIds)
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

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 permission=nauth.ACT_NTI_ADMIN,
			 context=IDataserverFolder,
			 name='ResetInquiry')
class ResetInquiryView(AbstractAuthenticatedView,
					   ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		values = super(ResetInquiryView, self).readInput()
		result = CaseInsensitiveDict(values)
		return result

	def _do_call(self):
		creator = None
		values = self.readInput()

		ntiid = values.get('ntiid') or values.get('inquiry')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity("Must provide an inquiry ntiid.")
		inquiry = component.getUtility(IQInquiry, name=ntiid)
		if inquiry is None:
			raise hexc.HTTPUnprocessableEntity("Must provide a valid inquiry.")

		entry = values.get('entry') or values.get('course')
		if entry:
			entry = find_object_with_ntiid(entry)
			entry = ICourseCatalogEntry(entry, None)
			if entry is None:
				raise hexc.HTTPUnprocessableEntity("Must provide a valid couse/entry ntiid.")

		if entry is None:
			username = values.get('username') or values.get('user')
			if not username:
				raise hexc.HTTPUnprocessableEntity("Must provide a username.")
			creator = User.get_user(username)
			if creator is None or not IUser.providedBy(creator):
				raise hexc.HTTPUnprocessableEntity("Must provide a valid user.")

		if entry is not None:
			course = ICourseInstance(entry)
			inquiries = IUsersCourseInquiries(course, None) or {}
			for inquiry in inquiries.values():
				if ntiid in inquiry:
					del inquiry[ntiid]
			return hexc.HTTPNoContent()

		if creator is not None:
			course = get_course_from_inquiry(inquiry, creator)
			if course is None:
				raise hexc.HTTPForbidden("Must be enrolled in a course.")

			course_inquiry = component.queryMultiAdapter((course, creator),
														 IUsersCourseInquiry)
			if course_inquiry and ntiid in course_inquiry:
				del course_inquiry[ntiid]
				return hexc.HTTPNoContent()
			else:
				raise hexc.HTTPUnprocessableEntity("User has not taken inquiry.")
