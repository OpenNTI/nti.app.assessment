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

from zope.intid.interfaces import IIntIds

from zope.security.interfaces import IPrincipal

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment import MessageFactory as _

from nti.app.assessment._integrity_check import check_assessment_integrity

from nti.app.assessment._question_map import _add_assessment_items_from_new_content
from nti.app.assessment._question_map import _remove_assessment_items_from_oldcontent

from nti.app.assessment.common import get_resource_site_name

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoint

from nti.app.assessment.views import parse_catalog_entry

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.internalization import read_body_as_external_object
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.maps import CaseInsensitiveDict

from nti.common.string import is_true

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IDataserverFolder

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.intid.common import removeIntId

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.hostpolicy import get_host_site

from nti.site.interfaces import IHostPolicyFolder

from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

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
		remove = is_true(values.get('remove'))
		integrity = check_assessment_integrity(remove)
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
				for assignmentId in set(history.keys()):  # snapshot
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

				for assignmentId in set(savepoint.keys()):  # snapshot
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
			 name='UnregisterAssessment')
class UnregisterAssessmentView(AbstractAuthenticatedView,
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
		ntiid = values.get('ntiid')
		if not ntiid:
			raise hexc.HTTPUnprocessableEntity(_("Invalid content NTIID."))

		force = is_true(values.get('force'))
		evaluation = find_object_with_ntiid(ntiid)
		evaluation = IQEvaluation(evaluation, None)
		if evaluation is None:
			raise hexc.HTTPUnprocessableEntity(_("Invalid evaluation object."))

		if not force and evaluation.isLocked():
			raise hexc.HTTPUnprocessableEntity(_("Evaluation object is locked."))

		intids = component.getUtility(IIntIds)
		folder = find_interface(evaluation, IHostPolicyFolder, strict=False)
		site = get_host_site(folder.__name__)
		with current_site(site):
			registry = site.getSiteManager()
			provided = iface_of_assessment(evaluation)
			unregisterUtility(registry, provided=provided, name=ntiid, force=force)
			if not IQEditableEvaluation.providedBy(evaluation):
				uid = intids.queryId(evaluation)
				if uid is not None:
					removeIntId(evaluation)

		return hexc.HTTPNoContent()

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

		force = is_true(values.get('force'))
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
		result[ITEM_COUNT] = result[TOTAL] = len(items)
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
		result[ITEM_COUNT] = result[TOTAL] = len(items)
		return result
