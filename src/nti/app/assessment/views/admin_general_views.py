#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from requests.structures import CaseInsensitiveDict

from zope import component

from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from zope.security.management import endInteraction
from zope.security.management import restoreInteraction

from persistent.list import PersistentList

from pyramid import httpexceptions as hexc

from pyramid.view import view_config

from nti.app.assessment import MessageFactory as _

from nti.app.assessment._integrity_check import check_assessment_integrity

from nti.app.assessment.synchronize import add_assessment_items_from_new_content
from nti.app.assessment.synchronize import remove_assessment_items_from_oldcontent

from nti.app.assessment.index import get_evaluation_catalog
from nti.app.assessment.index import get_submission_catalog

from nti.app.assessment.interfaces import IQEvaluations
from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.error import raise_json_error

from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.assessment import EVALUATION_INTERFACES

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.string import is_true

from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IDataserverFolder

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.intid.common import removeIntId

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.site.hostpolicy import get_host_site
from nti.site.hostpolicy import get_all_host_sites

from nti.site.interfaces import IHostPolicyFolder

from nti.site.utils import unregisterUtility

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

try:
    from nti.metadata import queue_add as metadata_queue_add
except ImportError:
    def metadata_queue_add(unused_obj):
        return


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             permission=nauth.ACT_NTI_ADMIN,
             context=IDataserverFolder,
             name='CheckAssessmentIntegrity')
class CheckAssessmentIntegrityView(AbstractAuthenticatedView,
                                   ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            data = super(CheckAssessmentIntegrityView, self).readInput(value)
            result = CaseInsensitiveDict(data)
        else:
            result = CaseInsensitiveDict(self.request.params)
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
             name='UnregisterAssessment')
class UnregisterAssessmentView(AbstractAuthenticatedView,
                               ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            values = super(UnregisterAssessmentView, self).readInput(value)
        else:
            values = self.request.params
        result = CaseInsensitiveDict(values)
        return result

    def removeIntId(self, evaluation=None):
        intids = component.getUtility(IIntIds)
        uid = intids.queryId(evaluation)
        if uid is not None:
            removeIntId(evaluation)

    def removeFromPackage(self, package, ntiid):
        def _recur(unit):
            container = IQAssessmentItemContainer(unit)
            if isinstance(container, (list, PersistentList)):
                del container[:]
                try:
                    del unit._question_map_assessment_item_container
                except AttributeError:
                    pass
                logger.warn("Invalid container for unit %r", unit)
            elif ntiid in container:
                evaluation = container[ntiid]
                container.pop(ntiid, None)
                self.removeIntId(evaluation)
            for child in unit.children or ():
                _recur(child)
        _recur(package)

    def _lookupAll(self, components, specs, provided, i, l, result, ntiid):
        if i < l:
            for spec in reversed(specs[i].__sro__):
                comps = components.get(spec)
                if comps:
                    self._lookupAll(comps,
                                    specs=specs,
                                    provided=provided,
                                    i=i + 1,
                                    l=l,
                                    result=result,
                                    ntiid=ntiid)
        else:
            for iface in reversed(provided):
                comps = components.get(iface)
                if comps and ntiid in comps:
                    result.append(comps)

    def _remove_evaluation_from_components(self, site_registry, ntiid):
        result = []
        required = ()
        order = len(required)
        for registry in site_registry.utilities.ro:  # must keep order
            byorder = registry._adapters
            if order >= len(byorder):
                continue
            components = byorder[order]
            extendors = EVALUATION_INTERFACES
            self._lookupAll(components, required, extendors,
                            0, order, result, ntiid)
            break  # break on first
        for cmps in result:
            logger.warn("Removing %s from components %s", ntiid, type(cmps))
            del cmps[ntiid]
        if result and hasattr(site_registry, 'changed'):
            site_registry.changed(site_registry)

    def _unregister_evaluation(self, registry, evaluation):
        interfaces = (iface_of_assessment(evaluation),) + EVALUATION_INTERFACES
        for provided in interfaces:
            if unregisterUtility(registry, provided=provided, name=evaluation.ntiid):
                logger.warn("%s has been unregistered", evaluation.ntiid)
                return True
        return False

    def _do_unregiser(self, evaluation, ntiid, site, values):
        # unregister the evaluation object
        with current_site(site):
            registry = site.getSiteManager()
            if not self._unregister_evaluation(registry, evaluation):
                # At this point the object was found, but registry  is in bad shape
                # so we remove it directly from the components
                self._remove_evaluation_from_components(registry, ntiid)

            if not IQEditableEvaluation.providedBy(evaluation):
                self.removeIntId(evaluation)
            else:
                course = ICourseInstance(evaluation, None)
                evals = IQEvaluations(course, None)
                if evals and ntiid in evals:
                    del evals[ntiid]

        package = evaluation.__parent__
        package = find_interface(package, IContentPackage, strict=False)
        if package is None:
            package = values.get('package')
            if package is not None:
                package = find_object_with_ntiid(ntiid)
            else:
                package = None

        package = IContentPackage(package, None)
        if package is not None and not IQEditableEvaluation.providedBy(evaluation):
            self.removeFromPackage(package, ntiid)

    def _do_call(self):
        values = self.readInput()
        ntiid = values.get('ntiid')
        if not ntiid:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Invalid object NTIID."),
                             },
                             None)

        force = is_true(values.get('force'))
        evaluation = find_object_with_ntiid(ntiid)
        evaluation = IQEvaluation(evaluation, None)
        if evaluation is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Invalid Evaluation object."),
                                 'ntiid': ntiid
                             },
                             None)

        if not force and evaluation.isLocked():
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Evaluation object is locked."),
                                 'ntiid': ntiid
                             },
                             None)

        folder = find_interface(evaluation, IHostPolicyFolder, strict=False)
        if folder is None:
            site = None
            name = values.get('site')
            if not name:
                for host_site in get_all_host_sites():  # check all sites
                    with current_site(host_site):
                        obj = component.queryUtility(IQEvaluation,
                                                     name=evaluation.ntiid)
                        if obj is not None:
                            logger.info("%s evaluation found at %s",
                                        ntiid,
                                        host_site.__name__)
                            site = host_site
                            break
            else:
                site = get_host_site(name)
        else:
            site = get_host_site(folder.__name__)

        if site is None:
            raise_json_error(self.request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': _(u"Invalid Evaluation site."),
                                 'ntiid': ntiid
                             },
                             None)
        # do removal
        endInteraction()
        try:
            self._do_unregiser(evaluation, ntiid, site, values)
        finally:
            restoreInteraction()
        return hexc.HTTPNoContent()


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             permission=nauth.ACT_NTI_ADMIN,
             context=IContentPackage,
             name='UnregisterAssessmentItems')
class UnregisterAssessmentItemsView(AbstractAuthenticatedView,
                                    ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            values = super(UnregisterAssessmentItemsView, self).readInput(value)
        else:
            values = self.request.params
        result = CaseInsensitiveDict(values)
        return result

    def _do_call(self):
        values = self.readInput()
        force = is_true(values.get('force'))
        site = IHostPolicyFolder(self.context)
        with current_site(site):
            items, unused = remove_assessment_items_from_oldcontent(self.context, force)
        result = LocatedExternalDict()
        result[ITEMS] = sorted(items.keys())
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             permission=nauth.ACT_NTI_ADMIN,
             context=IContentPackage,
             name='RegisterAssessmentItems')
class RegisterAssessmentItemsView(AbstractAuthenticatedView,
                                  ModeledContentUploadRequestUtilsMixin):

    def readInput(self, value=None):
        if self.request.body:
            values = super(RegisterAssessmentItemsView, self).readInput(value)
        else:
            values = self.request.params
        result = CaseInsensitiveDict(values)
        return result

    def _do_call(self):
        items = ()
        package = self.context
        result = LocatedExternalDict()
        key = package.does_sibling_entry_exist('assessment_index.json')
        if key is not None:
            site = IHostPolicyFolder(package)
            with current_site(site):
                items = add_assessment_items_from_new_content(package, key)
                main_container = IQAssessmentItemContainer(package)
                main_container.lastModified = key.lastModified
                result.lastModified = key.lastModified
        result[ITEMS] = sorted(items)
        result[ITEM_COUNT] = result[TOTAL] = len(items)
        return result


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             permission=nauth.ACT_NTI_ADMIN,
             request_method='POST',
             context=IEditableContentPackage,
             name='RemoveEvaluations')
class RemoveEvaluationsView(AbstractAuthenticatedView):

    def __call__(self):
        evaluations = IQEvaluations(self.context, None)
        if evaluations:
            evaluations.clear()
        return hexc.HTTPNoContent()


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             request_method='POST',
             permission=nauth.ACT_NTI_ADMIN,
             context=IDataserverFolder,
             name='RebuildEvaluationCatalog')
class RebuildEvaluationCatalogView(AbstractAuthenticatedView):

    def __call__(self):
        intids = component.getUtility(IIntIds)
        # clear indexes
        catalog = get_evaluation_catalog()
        for index in list(catalog.values()):
            index.clear()
        # reindex
        seen = set()
        for host_site in get_all_host_sites():  # check all sites
            with current_site(host_site):
                for _, evaluation in list(component.getUtilitiesFor(IQEvaluation)):
                    doc_id = intids.queryId(evaluation)
                    if doc_id is None or doc_id in seen:
                        continue
                    seen.add(doc_id)
                    catalog.index_doc(doc_id, evaluation)
                    metadata_queue_add(evaluation)
        result = LocatedExternalDict()
        result[ITEM_COUNT] = result[TOTAL] = len(seen)
        return result


@view_config(route_name='objects.generic.traversal',
             renderer='rest',
             request_method='POST',
             permission=nauth.ACT_NTI_ADMIN,
             context=IDataserverFolder,
             name='RebuildSubmissionCatalog')
class RebuildSubmissionCatalogView(AbstractAuthenticatedView):

    def _process_course(self, course, index, intids):
        result = 0
        for provided in (IUsersCourseAssignmentHistories, IUsersCourseInquiries):
            container = provided(course, None) or {}
            for user_data in list(container.values()):
                for obj in list(user_data.values()):
                    doc_id = intids.queryId(obj)
                    if doc_id is not None:
                        index.index_doc(doc_id, obj)
                        metadata_queue_add(obj)
                        result += 1
        return result

    def _process_site(self, index, intids, seen):
        result = 0
        catalog = component.queryUtility(ICourseCatalog)
        if catalog is None or catalog.isEmpty():
            return result
        for entry in catalog.iterCatalogEntries():
            course = ICourseInstance(entry)
            doc_id = intids.queryId(course)
            if doc_id is None or doc_id in seen:
                continue
            seen.add(doc_id)
            result += self._process_course(course, index, intids)
        return result

    def __call__(self):
        intids = component.getUtility(IIntIds)
        # clear indexes
        sub_catalog = get_submission_catalog()
        for index in list(sub_catalog.values()):
            index.clear()
        # reindex
        seen = set()
        total = self._process_site(sub_catalog, intids, seen)
        for host_site in get_all_host_sites():  # check all sites
            with current_site(host_site):
                total += self._process_site(sub_catalog, intids, seen)
        result = LocatedExternalDict()
        result[ITEM_COUNT] = result[TOTAL] = total
        return result
