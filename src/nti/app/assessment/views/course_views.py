#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from functools import partial

from pyramid.view import view_config
from pyramid.view import view_defaults

from requests.structures import CaseInsensitiveDict

from zope import component
from zope import lifecycleevent

from nti.app.assessment.common.evaluations import get_course_assignments

from nti.app.assessment.common.inquiries import get_course_inquiries

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.assessment.common import get_containerId

from nti.assessment.interfaces import IQAssignment

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

logger = __import__('logging').getLogger(__name__)


class CourseViewMixin(AbstractAuthenticatedView, BatchingUtilsMixin):

    _DEFAULT_BATCH_START = 0
    _DEFAULT_BATCH_SIZE = 30

    def _params(self):
        return CaseInsensitiveDict(self.request.params)
    
    def _get_mimeTypes(self):
        params = self._params()
        accept = params.get('accept') or params.get('mimeType')
        accept = accept.split(',') if accept else ()
        if accept and '*/*' not in accept:
            accept = {e.strip() for e in accept if e}
            accept.discard('')
        else:
            accept = ()
        return accept

    def _byOutline(self):
        params = self._params()
        outline = is_true(params.get('byOutline') or params.get('outline'))
        return outline

    def _filterBy(self, item, mimeTypes=()):
        mimeType = getattr(item, 'mimeType', None) \
                or getattr(item, 'mime_type', None)
        return bool(not mimeTypes or mimeType in mimeTypes)

    def _do_call(self, func):
        count = 0
        result = LocatedExternalDict()
        result.__name__ = self.request.view_name
        result.__parent__ = self.request.context
        self.request.acl_decoration = False
        outline = self._byOutline()
        mimeTypes = self._get_mimeTypes()
        items = result[ITEMS] = dict() if outline else list()
        for item in func():
            if not self._filterBy(item, mimeTypes):  # filter by
                continue
            count += 1
            if not outline:
                items.append(item)
            else:
                ntiid = get_containerId(item) or 'unparented'
                items.setdefault(ntiid, []).append(item)
        if not outline:
            self._batch_items_iterable(result, items)
        else:
            result[ITEM_COUNT] = count
        result[TOTAL] = count
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='AssessmentItems')
class CourseAssessmentItemsCatalogView(CourseViewMixin):

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
        func = partial(get_course_assignments,
                       instance,
                       do_filtering=do_filtering)
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


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='GetLockAssignments')
class GetLockAssignmentsView(CourseViewMixin):

    def _filterBy(self, item, mimeTypes=()):
        result = CourseViewMixin._filterBy(self, item, mimeTypes=mimeTypes)
        return result and item.isLocked()

    def __call__(self):
        instance = ICourseInstance(self.request.context)
        func = partial(get_course_assignments, instance, do_filtering=False)
        return self._do_call(func)


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='GetLockedAssignments')
class GetLockedAssignmentsView(GetLockAssignmentsView):
    pass


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='POST',
               name='LockAllAssignments')
class LockAllAssignmentsView(AbstractAuthenticatedView):

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = []
        course = ICourseInstance(self.context)
        for item in get_course_assignments(course, sort=False, do_filtering=False):
            assesment = component.queryUtility(IQAssignment, name=item.ntiid)
            if assesment is not None and not assesment.isLocked():
                assesment.lock()
                items.append(assesment.ntiid)
                lifecycleevent.modified(assesment)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result


@view_config(context=ICourseInstance)
@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='POST',
               name='UnlockAllAssignments')
class UnlockAllAssignmentsView(AbstractAuthenticatedView):

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = []
        course = ICourseInstance(self.context)
        for item in get_course_assignments(course, sort=False, do_filtering=False):
            assesment = component.queryUtility(IQAssignment, name=item.ntiid)
            if assesment is not None and assesment.isLocked():
                assesment.unlock()
                items.append(assesment.ntiid)
                lifecycleevent.modified(assesment)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result
