#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Implementation of the assessment question map and supporting
functions to maintain it.

.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time
from collections import OrderedDict

from zope import component
from zope import interface

from zope.component.hooks import getSite

from zope.container.contained import Contained

from zope.container.btree import BTreeContainer

from zope.deprecation import deprecated

from zope.intid.interfaces import IIntIds

from ZODB.interfaces import IConnection

from BTrees.OOBTree import OOBTree

from persistent.list import PersistentList

from persistent.mapping import PersistentMapping

from nti.assessment._question_index import QuestionIndex
from nti.assessment._question_index import _ntiid_object_hook

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.assessment.interfaces import SURVEY_MIME_TYPE
from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import QUESTION_SET_MIME_TYPE

from nti.contentlibrary.indexed_data import get_site_registry

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contentlibrary.synchronize import ContentPackageSyncResults

from nti.dublincore.time_mixins import PersistentCreatedAndModifiedTimeObject

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.externalization.persistence import NoPickle

from nti.externalization.proxy import removeAllProxies

from nti.intid.common import addIntId

from nti.publishing.interfaces import IPublishable
from nti.publishing.interfaces import INoPublishLink

from nti.site.utils import registerUtility

from nti.wref.interfaces import IWeakRef

NTIID = StandardExternalFields.NTIID

deprecated('_AssessmentItemContainer', 'Replaced with a persistent mapping')
class _AssessmentItemContainer(PersistentList):
    pass


deprecated('_AssessmentItemStore', 'Deprecated Storage Mode')
class _AssessmentItemStore(BTreeContainer):
    pass


deprecated('_AssessmentItemBucket', 'Deprecated Storage Mode')
class _AssessmentItemBucket(PersistentMapping,
                            PersistentCreatedAndModifiedTimeObject,
                            Contained):
    assessments = PersistentMapping.values


@component.adapter(IContentUnit)
@interface.implementer(IQAssessmentItemContainer)
class _AssessmentItemOOBTree(OOBTree,
                             PersistentCreatedAndModifiedTimeObject,
                             Contained):

    _SET_CREATED_MODTIME_ON_INIT = False

    def __init__(self, *args, **kwargs):
        OOBTree.__init__(self)
        PersistentCreatedAndModifiedTimeObject.__init__(self, *args, **kwargs)

    def append(self, item):
        self[item.ntiid] = item

    def extend(self, items):
        for item in items or ():
            self.append(item)

    def assessments(self):
        return list(self.values())


@component.adapter(IContentUnit)
@interface.implementer(IQAssessmentItemContainer)
def ContentUnitAssessmentItems(unit):
    # Instead of using annotations on the content objects, we
    # use an atttibute since we are seing connection problems
    # during unit tests
    try:
        result = unit._question_map_assessment_item_container
    except AttributeError:
        result = unit._question_map_assessment_item_container = _AssessmentItemOOBTree()
        result.createdTime = time.time()
        result.lastModified = -1
    # make sure there is lineage
    if result.__parent__ is None:
        result.__parent__ = unit
        result.__name__ = '_question_map_assessment_item_container'
    return result


def new_sync_results(package):
    site = getSite()
    result = ContentPackageSyncResults(Site=getattr(site, '__name__', None),
                                       ContentPackageNTIID=package.ntiid)
    return result


def get_assess_item_dict(base):
    """
    Make sure we iterate through our assessment dict in a
    deterministic order. This ensures everything is registered
    the same way (including the correct containers) every time.
    """
    def _get_mime(obj):
        # Except either an assessment object here
        # or an incoming assessment dict.
        try:
            result = obj.mime_type
        except AttributeError:
            result = obj.get('MimeType')
        return result

    result = OrderedDict()
    for mime_type in (ASSIGNMENT_MIME_TYPE,
                      SURVEY_MIME_TYPE,
                      QUESTION_SET_MIME_TYPE,
                      None):
        for key, item in base.items():
            if key in result:
                continue
            elif mime_type == None:
                # Everything else
                result[key] = item
            elif _get_mime(item) == mime_type:
                result[key] = item
    return result


@NoPickle
class QuestionMap(QuestionIndex):
    """
    Originally a single utility that stored all of the assessment items,
    now primarily a place for the algorithm to live, with a bit of bookkeeping
    for tests.

    Other than its event handlers, it must not be used during production code.
    Specifically, one must not rely on being able to reach anything
    from it using its dictionary interface; the global utility WILL NOT
    be in sync with what it available in sub-libraries.
    """

    def _get_by_file(self):
        # subclasses can override to use persistent storage
        return {}

    def _store_object(self, k, v):
        pass

    def _registry_utility(self, registry, component, provided, name, event=False):
        if not IWeakRef.providedBy(component):  # no weak refs
            registerUtility(registry,
                            component,
                            provided=provided,
                            name=name,
                            event=event)
            logger.debug("(%s,%s) has been registered",
                         provided.__name__, name)

    def _get_registry(self, registry=None):
        return get_site_registry(registry)

    def _register_and_canonicalize(self, things_to_register, registry=None):
        registry = self._get_registry(registry)
        result = QuestionIndex._register_and_canonicalize(self,
                                                          things_to_register,
                                                          registry)
        return result

    def _publish_object(self, item):
        if IPublishable.providedBy(item) and not item.is_published():
            item.publish(event=False)  # by default
            interface.alsoProvides(item, INoPublishLink)

    def _connection(self, registry=None):
        registry = self._get_registry(registry)
        if registry == component.getGlobalSiteManager():
            return None
        else:
            return IConnection(registry, None)

    def _intid_register(self, item, registry=None, intids=None, connection=None):
        # We always want to register and persist our assessment items,
        # even from the global library.
        registry = self._get_registry(registry)
        intids = component.queryUtility(IIntIds) if intids is None else intids
        if connection is None:
            connection = self._connection(registry)
        if connection is not None:  # Tests/
            if IConnection(item, None) is None:
                connection.add(item)
            if intids is not None and intids.queryId(item) is None:
                addIntId(item)
            return True
        return False

    def _process_assessments(self,
                             assessment_item_dict,
                             containing_hierarchy_key,
                             content_package,
                             by_file,
                             level_ntiid=None,
                             signatures_dict=None,
                             registry=None,
                             sync_results=None,
                             key_lastModified=None):
        """
        Returns a set of object that should be placed in the registry, and then
        canonicalized.
        """

        parent = None
        signatures_dict = signatures_dict or {}
        intids = component.queryUtility(IIntIds)
        library = component.queryUtility(IContentPackageLibrary)
        parents_questions = IQAssessmentItemContainer(content_package)

        # XXX: remove
        hierarchy_ntiids = set()
        hierarchy_ntiids.add(content_package.ntiid)

        if level_ntiid and library is not None:
            containing_content_units = library.pathToNTIID(level_ntiid)
            if containing_content_units:
                parent = containing_content_units[-1]
                parents_questions = IQAssessmentItemContainer(parent)
                hierarchy_ntiids.update(
                    x.ntiid for x in containing_content_units
                )

        result = set()
        registry = self._get_registry(registry)
        key_lastModified = key_lastModified or time.time()

        assess_dict = get_assess_item_dict(assessment_item_dict)
        for ntiid, v in assess_dict.items():
            __traceback_info__ = ntiid, v

            factory = find_factory_for(v)
            assert factory is not None

            obj = factory()
            provided = iface_of_assessment(obj)
            registered = registry.queryUtility(provided, name=ntiid)
            if registered is None:
                update_from_external_object(obj, v, require_updater=True,
                                            notify=False,
                                            object_hook=_ntiid_object_hook)
                obj.ntiid = ntiid
                obj.signature = signatures_dict.get(ntiid)
                self._store_object(ntiid, obj)

                things_to_register = self._explode_object_to_register(obj)

                for item in things_to_register:
                    # get unproxied object
                    thing_to_register = removeAllProxies(item)
                    thing_to_register.createdTime = key_lastModified
                    thing_to_register.lastModified = key_lastModified
                    # check registry
                    ntiid = thing_to_register.ntiid
                    provided = iface_of_assessment(thing_to_register)
                    if ntiid and registry.queryUtility(provided, name=ntiid) is None:
                        result.add(thing_to_register)

                        # register assesment
                        self._registry_utility(registry,
                                               component=thing_to_register,
                                               provided=provided,
                                               name=ntiid)
                        # TODO: We are only partially supporting having question/sets
                        # used multiple places. When we get to that point, we need to
                        # handle it by noting on each assessment object where it is
                        # registered
                        if thing_to_register.__parent__ is None and parent is not None:
                            thing_to_register.__parent__ = parent
                        else:
                            logger.warn("Could not set parent for %s. %s %s", ntiid,
                                        thing_to_register.__parent__, parent)

                        # publish item
                        self._publish_object(thing_to_register)

                        # add to container and get and intid
                        self._intid_register(thing_to_register,
                                             intids=intids,
                                             registry=registry)
                        parents_questions.append(thing_to_register)

                        # register in sync results
                        if sync_results is not None:
                            sync_results.add_assessment(thing_to_register, 
                                                        False)
                    elif ntiid and ntiid not in parents_questions:
                        # Child item locked/edited.
                        # Update parent and put in parent container.
                        parents_questions.append(thing_to_register)
                        thing_to_register.__parent__ = parent
            else:
                # These are locked/edited objects. We want to
                # make sure we place in parent container and make sure
                # we update lineage to the new content unit objects.
                obj = registered
                obj.__parent__ = parent
                self._store_object(ntiid, obj)
                things_to_register = self._explode_object_to_register(obj)
                for item in things_to_register:
                    item = removeAllProxies(item)
                    item.__parent__ = parent
                if ntiid not in parents_questions:
                    parents_questions.append(registered)

            if containing_hierarchy_key:
                assert containing_hierarchy_key in by_file, \
                       "Container for file must already be present"
                by_file[containing_hierarchy_key].append(obj)

        return result

    def _from_index_entry(self,
                          index,
                          content_package,
                          by_file,
                          nearest_containing_key=None,
                          nearest_containing_ntiid=None,
                          registry=None,
                          sync_results=None,
                          key_lastModified=None):
        """
        Called with an entry for a file or (sub)section. May or may not have
        children of its own.

        Returns a set of things to register and canonicalize.

        """
        key_for_this_level = nearest_containing_key
        index_key = index.get('filename')
        if index_key:
            factory = list
            key_for_this_level = content_package.make_sibling_key(index_key)
            if key_for_this_level in by_file:
                # Across all indexes, every filename key should be unique.
                # We rely on this property when we lookup the objects to return
                # We make an exception for index.html, due to a duplicate bug in
                # old versions of the exporter, but we ensure we can't put any
                # questions on it
                if index_key == 'index.html':
                    logger.warn("Duplicate 'index.html' entry in %s; update content",
                                content_package)
                else:
                    __traceback_info__ = index_key, key_for_this_level
                    logger.warn("Second entry for the same file %s,%s",
                                index_key, key_for_this_level)

            by_file[key_for_this_level] = factory()

        things_to_register = set()
        key_lastModified = key_lastModified or time.time()
        level_ntiid = index.get(NTIID) or nearest_containing_ntiid
        items = self._process_assessments(index.get("AssessmentItems", {}),
                                          key_for_this_level,
                                          content_package,
                                          by_file,
                                          level_ntiid,
                                          index.get("Signatures"),
                                          registry=registry,
                                          sync_results=sync_results,
                                          key_lastModified=key_lastModified)
        things_to_register.update(items)

        for child_item in index.get('Items', {}).values():
            items = self._from_index_entry(child_item,
                                           content_package,
                                           by_file,
                                           nearest_containing_key=key_for_this_level,
                                           nearest_containing_ntiid=level_ntiid,
                                           registry=registry,
                                           sync_results=sync_results,
                                           key_lastModified=key_lastModified)
            things_to_register.update(items)

        return things_to_register

    def _from_root_index(self,
                         assessment_index_json,
                         content_package,
                         registry=None,
                         sync_results=None,
                         key_lastModified=None):
        """
        The top-level is handled specially: ``index.html`` is never allowed to have
        assessment items.
        """
        __traceback_info__ = assessment_index_json, content_package

        assert 'Items' in assessment_index_json, "Root must contain 'Items'"

        root_items = assessment_index_json['Items']
        if not root_items:
            logger.warn("Ignoring assessment index that contains no assessments at any level %s",
                        content_package)
            return
        key_lastModified = key_lastModified or time.time()

        # 7.2017 We used to validate we did not have items directly in the root_ntiid.
        # That should no longer be a concern.
        by_file = self._get_by_file()

        things_to_register = set()
        if sync_results is None:
            sync_results = new_sync_results(content_package)

        for child_ntiid, child_index in root_items.items():
            __traceback_info__ = child_ntiid, child_index, content_package
            # Each of these should have a filename. If they do not, they obviously
            # cannot contain  assessment items. The condition of a missing/bad filename
            # has been seen in jacked-up content that abuses the section hierarchy
            # (skips levels) and/or jacked-up themes/configurations  that split incorrectly.
            # 6.2017 - this constraint may no longer be necessary; so let's
            # just warn.
            if     'filename' not in child_index \
                or not child_index['filename'] \
                or child_index['filename'].startswith('index.html#'):
                logger.warn("Invalid child with invalid filename '%s'; cannot contain assessments: %s",
                            child_index.get('filename', ''),
                            child_index)

            parsed = self._from_index_entry(child_index,
                                            content_package,
                                            by_file,
                                            registry=registry,
                                            sync_results=sync_results,
                                            key_lastModified=key_lastModified,
                                            nearest_containing_ntiid=child_ntiid,)
            things_to_register.update(parsed)

        # register assessment items
        registered = self._register_and_canonicalize(things_to_register,
                                                    registry)
        # For tests and such, sort
        for questions in by_file.values():
            questions.sort(key=lambda q: q.ntiid)

        registered = {x.ntiid for x in registered}
        return by_file, registered
