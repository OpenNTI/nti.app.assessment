#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from requests.structures import CaseInsensitiveDict

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.appserver.dataserver_pyramid_views import GenericGetView

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

OID = StandardExternalFields.OID
ITEMS = StandardExternalFields.ITEMS
NTIID = StandardExternalFields.NTIID
TOTAL = StandardExternalFields.TOTAL
MIMETYPE = StandardExternalFields.MIMETYPE
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


@view_config(context=IQEvaluations)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='GET',
               permission=nauth.ACT_CONTENT_EDIT)
class EvaluationsGetView(AbstractAuthenticatedView, 
						 BatchingUtilsMixin):

    _DEFAULT_BATCH_SIZE = 50
    _DEFAULT_BATCH_START = 0

    def _get_mimeTypes(self):
        params = CaseInsensitiveDict(self.request.params)
        accept = params.get('accept') or params.get('mimeTypes') or ''
        accept = accept.split(',') if accept else ()
        if accept and '*/*' not in accept:
            accept = {e.strip().lower() for e in accept if e}
            accept.discard('')
        else:
            accept = ()
        return accept

    def _do_call(self, evaluations):
        result = LocatedExternalDict()
        result.__parent__ = evaluations
        result.__name__ = self.request.view_name
        result.lastModified = evaluations.lastModified
        mimeTypes = self._get_mimeTypes()
        items = result[ITEMS] = []
        if mimeTypes:
            items.extend(
				x for x in evaluations.values() if x.mimeType in mimeTypes
			)
        else:
            items.extend(evaluations.values())

        result['TotalItemCount'] = len(items)
        self._batch_items_iterable(result, items)
        result[ITEM_COUNT] = len(result[ITEMS])
        return result

    def __call__(self):
        return self._do_call(self.context)


@view_config(context=ICourseCatalogEntry)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               request_method='GET',
               name="CourseEvaluations",
               permission=nauth.ACT_CONTENT_EDIT)
class CatalogEntryEvaluationsView(EvaluationsGetView):

    def __call__(self):
        course = ICourseInstance(self.context)
        evaluations = IQEvaluations(course)
        return self._do_call(evaluations)


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             context=IQEvaluation,
             request_method='GET',
             permission=nauth.ACT_READ)
class EvaluationGetView(GenericGetView):

    def __call__(self):
        result = GenericGetView.__call__(self)
        # XXX Check than only editors can have access
        # to unpublished evaluations.
        if 		IQEditableEvaluation.providedBy(result) \
			and not result.is_published() \
            and not has_permission(nauth.ACT_CONTENT_EDIT, result, self.request):
            raise hexc.HTTPForbidden()
        return result
