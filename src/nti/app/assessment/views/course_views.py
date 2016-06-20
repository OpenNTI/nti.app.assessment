#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from functools import partial

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import get_course_inquiries
from nti.app.assessment.common import get_course_assignments

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.common.maps import CaseInsensitiveDict

from nti.common.string import is_true

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssessmentItemCatalog

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

class CourseViewMixin(AbstractAuthenticatedView, BatchingUtilsMixin):

	_DEFAULT_BATCH_START = 0
	_DEFAULT_BATCH_SIZE = 20

	def _get_mimeTypes(self):
		params = CaseInsensitiveDict(self.request.params)
		result = params.get('accept') or params.get('mimeType')
		if result:
			result = set(result.split(','))
		return result or ()

	def _byOutline(self):
		params = CaseInsensitiveDict(self.request.params)
		outline = is_true(params.get('byOutline') or params.get('outline'))
		return outline

	def _do_call(self, func):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context
		self.request.acl_decoration = False
		count = 0
		outline = self._byOutline()
		mimeTypes = self._get_mimeTypes()
		items = result[ITEMS] = dict() if outline else list()
		for item in func():
			if mimeTypes:  # filter by
				mt = getattr(item, 'mimeType', None) or	getattr(item, 'mime_type', None)
				if mt not in mimeTypes:
					continue
			count += 1
			if not outline:
				items.append(item)
			else:
				unit = item.__parent__
				ntiid = unit.ntiid if unit is not None else 'unparented'
				items.setdefault(ntiid, []).append(item)
		if not outline: 
			self._batch_items_iterable(result, items)
		else:
			result[ITEM_COUNT] = count
		result[TOTAL] =  count
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_CONTENT_EDIT,
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
			   permission=nauth.ACT_CONTENT_EDIT,
			   request_method='GET',
			   name='Assignments')
class CourseAssignmentsView(CourseViewMixin):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		params = CaseInsensitiveDict(self.request.params)
		do_filtering = is_true(params.get('filter'))
		func = partial(get_course_assignments, instance, do_filtering=do_filtering)
		return self._do_call(func)

@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_CONTENT_EDIT,
			   request_method='GET',
			   name='Inquiries')
class CourseInquiriesView(CourseViewMixin):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		func = partial(get_course_inquiries, instance, do_filtering=False)
		return self._do_call(func)
