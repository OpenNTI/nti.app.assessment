#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from requests.structures import CaseInsensitiveDict

from zope import lifecycleevent

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common.evaluations import get_unit_assessments
from nti.app.assessment.common.evaluations import get_content_packages_assessment_items

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IEditableContentPackage

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

    def _allowBy(self, item, mimeTypes=()):
        mt =   getattr(item, 'mimeType', None) \
            or getattr(item, 'mime_type', None)
        return bool(not mimeTypes or mt in mimeTypes)

    def _unit_assessments(self):
        if IContentPackage.providedBy(self.context):
            return get_content_packages_assessment_items(self.context)
        else:
            return get_unit_assessments(self.context)

    def _authored_assessments(self):
        evals = IQEvaluations(self.context, None)
        return evals.values() if evals else ()
        
    def _all_assessments(self):
        if IEditableContentPackage.providedBy(self.context):
            return self._authored_assessments()
        else:
            return self._unit_assessments()

    def _filter_assessments(self):
        mimeTypes = self._get_mimeTypes()
        for item in self._all_assessments():
            if self._allowBy(item, mimeTypes):
                yield item
            
    def _do_call(self):
        count = 0
        result = LocatedExternalDict()
        result.__name__ = self.request.view_name
        result.__parent__ = self.request.context
        self.request.acl_decoration = False
        items = result[ITEMS] = list()
        for item in self._filter_assessments():
            count += 1
            items.append(item)
        self._batch_items_iterable(result, items)
        result[TOTAL] = count
        return result

    def __call__(self):
        return self._do_call()

    
@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='GET',
               name='AssessmentItems')
class ContentUnitAssessmentItemsCatalogView(ContentUnitViewMixin):
    pass


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

    def _allowBy(self, item, mimeTypes=()):
        result = ContentUnitViewMixin._allowBy(self, item, mimeTypes=mimeTypes)
        return result and (IRecordable.providedBy(item) and item.isLocked())


@view_config(context=IContentUnit)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               permission=nauth.ACT_CONTENT_EDIT,
               request_method='POST',
               name='LockAllAssignments')
class LockAllAssignmentsView(ContentUnitViewMixin):
    
    def _params(self):
        result = CaseInsensitiveDict(self.request.params)
        result['accept'] = result['mimeType'] = ALL_ASSIGNMENT_MIME_TYPES
        return result
    
    def _allowBy(self, item, mimeTypes=()):
        result = ContentUnitViewMixin._allowBy(self, item, mimeTypes=mimeTypes)
        return result and (IRecordable.providedBy(item) and not item.isLocked())

    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = []
        for assesment in self._filter_assessments():
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
class UnlockAllAssignmentsView(ContentUnitViewMixin):
    
    def _params(self):
        result = CaseInsensitiveDict(self.request.params)
        result['accept'] = result['mimeType'] = ALL_ASSIGNMENT_MIME_TYPES
        return result
    
    def _allowBy(self, item, mimeTypes=()):
        result = ContentUnitViewMixin._allowBy(self, item, mimeTypes=mimeTypes)
        return result and (IRecordable.providedBy(item) and item.isLocked())
    
    def __call__(self):
        result = LocatedExternalDict()
        items = result[ITEMS] = []
        for assesment in self._filter_assessments():
            assesment.unlock()
            items.append(assesment.ntiid)
            lifecycleevent.modified(assesment)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result
