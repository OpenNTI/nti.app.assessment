#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from functools import partial

from requests.structures import CaseInsensitiveDict

from zope import lifecycleevent

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common.evaluations import get_unit_assessments

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.assessment.interfaces import IQAssignment

from nti.contentlibrary.interfaces import IContentUnit

from nti.assessment.interfaces import INQUIRY_MIME_TYPES
from nti.assessment.interfaces import ALL_ASSIGNMENT_MIME_TYPES

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.recorder.interfaces import IRecordable

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


class ContentUnitViewMixin(AbstractAuthenticatedView, BatchingUtilsMixin):

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

    def _filterBy(self, item, mimeTypes=()):
        mt =   getattr(item, 'mimeType', None) \
            or getattr(item, 'mime_type', None)
        return bool(not mimeTypes or mt in mimeTypes)

    def _do_call(self, func):
        count = 0
        result = LocatedExternalDict()
        result.__name__ = self.request.view_name
        result.__parent__ = self.request.context
        self.request.acl_decoration = False
        mimeTypes = self._get_mimeTypes()
        items = result[ITEMS] = list()
        for item in func():
            if not self._filterBy(item, mimeTypes):  # filter by
                continue
            count += 1
            items.append(item)
        self._batch_items_iterable(result, items)
        result[TOTAL] = count
        return result


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='AssessmentItems')
class ContentUnitAssessmentItemsCatalogView(ContentUnitViewMixin):

    def __call__(self):
        func = partial(get_unit_assessments, self.context)
        return self._do_call(func)


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='Assignments')
class ContentUnitAssignmentsView(ContentUnitViewMixin):

    def _params(self):
        result = CaseInsensitiveDict(self.request.params)
        result['accept'] = result['mimeType'] = ','.join(ALL_ASSIGNMENT_MIME_TYPES)
        return result
        
    def __call__(self):
        func = partial(get_unit_assessments, self.context)
        return self._do_call(func)


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='Inquiries')
class CourseInquiriesView(ContentUnitViewMixin):

    def _params(self):
        result = CaseInsensitiveDict(self.request.params)
        result['accept'] = result['mimeType'] = ','.join(INQUIRY_MIME_TYPES)
        return result

    def __call__(self):
        func = partial(get_unit_assessments, self.context)
        return self._do_call(func)


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='GetLockAssignments')
class GetLockAssignmentsView(ContentUnitViewMixin):

    def _params(self):
        result = CaseInsensitiveDict(self.request.params)
        result['accept'] = result['mimeType'] = ALL_ASSIGNMENT_MIME_TYPES
        return result

    def _filterBy(self, item, mimeTypes=()):
        result = ContentUnitViewMixin._filterBy(self, item, mimeTypes=mimeTypes)
        return result and item.isLocked()

    def __call__(self):
        func = partial(get_unit_assessments, self.context)
        return self._do_call(func)


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='POST',
               name='LockAllAssignments')
class LockAllAssignmentsView(AbstractAuthenticatedView):

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = []
        for assesment in get_unit_assessments(self.context):
            if not IQAssignment.providedBy(assesment):
                continue
            if IRecordable.providedBy(assesment) and not assesment.isLocked():
                assesment.lock()
                items.append(assesment.ntiid)
                lifecycleevent.modified(assesment)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='POST',
               name='UnlockAllAssignments')
class UnlockAllAssignmentsView(AbstractAuthenticatedView):

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = []
        for assesment in get_unit_assessments(self.context):
            if not IQAssignment.providedBy(assesment):
                continue
            if IRecordable.providedBy(assesment) and assesment.isLocked():
                assesment.unlock()
                items.append(assesment.ntiid)
                lifecycleevent.modified(assesment)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result
