#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component

from zope.intid.interfaces import IIntIds

from zope.lifecycleevent.interfaces import IObjectAddedEvent
from zope.lifecycleevent.interfaces import IObjectRemovedEvent
from zope.lifecycleevent.interfaces import IObjectModifiedEvent

from nti.app.assessment._question_map import QuestionMap
from nti.app.assessment._question_map import new_sync_results
from nti.app.assessment._question_map import get_assess_item_dict

from nti.app.assessment.common.evaluations import get_content_packages_assessment_items

from nti.assessment._question_index import _load_question_map_json

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contentlibrary.interfaces import IContentPackage
from nti.contentlibrary.interfaces import IEditableContentPackage
from nti.contentlibrary.interfaces import IContentPackageSyncResults

from nti.intid.common import removeIntId

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.publishing.interfaces import IObjectPublishedEvent

from nti.recorder.interfaces import IRecordable

from nti.recorder.record import copy_transaction_history
from nti.recorder.record import remove_transaction_history

from nti.site.utils import unregisterUtility

logger = __import__('logging').getLogger(__name__)


def get_sync_results(content_package, event):
    all_results = getattr(event, "results", None)
    if not all_results or not IContentPackageSyncResults.providedBy(all_results[-1]):
        result = new_sync_results(content_package)
        if all_results is not None:
            all_results.append(result)
    elif all_results[-1].ContentPackageNTIID != content_package.ntiid:
        result = new_sync_results(content_package)
        all_results.append(result)
    else:
        result = all_results[-1]
    return result


def is_obj_locked(context):
    return IRecordable.providedBy(context) and context.isLocked()


def can_be_removed(registered, force=False):
    result = registered is not None \
        and (force or not is_obj_locked(registered))
    return result


def populate_question_map_json(asm_index_json,
                               content_package,
                               registry=None,
                               sync_results=None,
                               question_map=None,
                               key_lastModified=None):
    result = None
    if asm_index_json:
        if sync_results is None:
            sync_results = new_sync_results(content_package)

        question_map = QuestionMap() if question_map is None else question_map
        # pylint: disable=protected-access
        result = question_map._from_root_index(asm_index_json,
                                               content_package,
                                               registry=registry,
                                               sync_results=sync_results,
                                               key_lastModified=key_lastModified)
        result = None if result is None else result[1]  # registered
    return result or set()


def populate_question_map_from_text(question_map,
                                    asm_index_text,
                                    content_package,
                                    registry=None,
                                    sync_results=None,
                                    key_lastModified=None):
    index = _load_question_map_json(asm_index_text)
    return populate_question_map_json(asm_index_json=index,
                                      registry=registry,
                                      question_map=question_map,
                                      sync_results=sync_results,
                                      content_package=content_package,
                                      key_lastModified=key_lastModified)


def add_assessment_items_from_new_content(content_package, key=None, sync_results=None):
    if sync_results is None:
        sync_results = new_sync_results(content_package)

    if key is None:
        key = content_package.does_sibling_entry_exist('assessment_index.json')
    key_lastModified = key.lastModified if key is not None else None

    question_map = QuestionMap()
    asm_index_text = key.readContentsAsText()
    result = populate_question_map_from_text(question_map,
                                             asm_index_text,
                                             content_package,
                                             sync_results=sync_results,
                                             key_lastModified=key_lastModified)

    logger.info("%s assessment item(s) read from %s %s",
                len(result or ()), content_package, key)
    return result


def get_last_mod_namespace(content_package):
    return '%s.%s.LastModified' % (content_package.ntiid, 'assessment_index.json')


def needs_load_or_update(content_package):
    key = content_package.does_sibling_entry_exist('assessment_index.json')
    if not key:
        return
    main_container = IQAssessmentItemContainer(content_package)
    if key.lastModified <= main_container.lastModified:
        logger.info("No change to %s since %s, ignoring",
                    key,
                    key.modified)
        return
    return key


@component.adapter(IContentPackage, IObjectAddedEvent)
def on_content_package_added(package, event, key=None):
    """
    Assessment items have their NTIID as their __name__, and the NTIID of 
    their primary container within this context as their __parent__
    (that should really be the hierarchy entry)
    """
    if IEditableContentPackage.providedBy(package):
        return set()
    result = None
    # let other callers give us the key
    key = key or needs_load_or_update(package)
    if key is not None:
        logger.info("Reading/Adding assessment items from new content %s %s %s",
                    package, key, event)
        sync_results = get_sync_results(package, event)
        result = add_assessment_items_from_new_content(package, key, 
                                                       sync_results)
        # mark last modified
        container = IQAssessmentItemContainer(package)
        container.lastModified = key.lastModified
    return result or set()


def remove_assessment_items_from_oldcontent(package, force=False, sync_results=None):
    if sync_results is None:
        sync_results = new_sync_results(package)

    # Unregister the things from the component registry.
    # We SHOULD be run in the registry where the library item was initially
    # loaded. (We use the context argument to check)
    # 1) This doesn't properly handle the case of
    # having references in different content units; we approximate
    sm = component.getSiteManager()
    if component.getSiteManager(package) is not sm:
        # This could be an assertion
        logger.warn("Removing assessment items from wrong site %s "
                    "should be %s; may not work",
                    sm, component.getSiteManager(package))

    result = dict()
    intids = component.queryUtility(IIntIds)  # test mode

    def _remove(container, name, item):
        if name not in result:
            result[name] = item
            provided = iface_of_assessment(item)
            # unregister utility
            if not unregisterUtility(sm, provided=provided, name=name):
                logger.warn("Could not unregister %s from %s", name, sm)
            else:
                logger.debug("(%s,%s) has been unregistered",
                             provided.__name__, name)
            # unregister from intid
            if intids is not None and intids.queryId(item) is not None:
                removeIntId(item)
        # always remove from container
        container.pop(name, None)

    def _unregister(unit, ntiids_to_ignore):
        unit_items = IQAssessmentItemContainer(unit)
        items = get_assess_item_dict(unit_items)
        for name, item in items.items():
            if name not in ntiids_to_ignore:
                _remove(unit_items, name, item)
        # reset dates
        unit_items.lastModified = unit_items.createdTime = -1

        for child in unit.children or ():
            _unregister(child, ntiids_to_ignore)

    def _gather_to_ignore(unit, to_ignore_accum):
        unit_items = IQAssessmentItemContainer(unit)
        items = get_assess_item_dict(unit_items)
        for name, item in items.items():
            if not can_be_removed(item, force):
                provided = iface_of_assessment(item)
                logger.warn("Object (%s,%s) is locked cannot be removed during sync",
                            provided.__name__, name)
                # Make sure we add to the ignore list all items that are exploded
                # so they are not processed
                exploded = QuestionMap.explode_object_to_register(item)
                to_ignore_accum.update(x.ntiid for x in exploded or ())
        for child in unit.children or ():
            _gather_to_ignore(child, to_ignore_accum)

    # We make a first pass to gather all things to be ignored, this
    # is to ensure, if for example, a question is in multiple content
    # units (and in a locked assignment), we do not overwrite (register)
    # its state, leaving the item in the assignment stale.
    _ntiids_to_ignore = set()
    _gather_to_ignore(package, _ntiids_to_ignore)
    _unregister(package, _ntiids_to_ignore)

    # register locked
    for ntiid in _ntiids_to_ignore:
        sync_results.add_assessment(ntiid, locked=True)

    return result, _ntiids_to_ignore


@component.adapter(IContentPackage, IObjectRemovedEvent)
def on_content_package_removed(package, event=None, force=True):
    if IEditableContentPackage.providedBy(package):
        return set(), set()
    sync_results = get_sync_results(package, event)
    logger.info("Removing assessment items from old content %s %s",
                package, event)
    result, locked_ntiids = remove_assessment_items_from_oldcontent(package, force,
                                                                    sync_results)
    return set(result.values()), set(locked_ntiids)


@component.adapter(IContentPackage, IObjectPublishedEvent)
def on_content_package_unpublished(package, unused_event=None):
    if not IEditableContentPackage.providedBy(package):
        remove_assessment_items_from_oldcontent(package, force=True)


def transfer_locked_items_to_content_package(package, added_items, locked_ntiids):
    """
    If we have locked items, but they do not exist in the added items, add
    them to our content package so that it's possible to remove them if
    they are ever unlocked.
    """
    added_ntiids = set(x.ntiid for x in added_items or ())
    missing_ntiids = set(locked_ntiids) - set(added_ntiids)
    for ntiid in missing_ntiids:
        # Try to store in its existing content unit container; otherwise
        # fall back to storing on the content package.
        missing_item = find_object_with_ntiid(ntiid)
        item_parent = find_object_with_ntiid(missing_item.containerId)
        logger.info('Attempting to remove item from content, but item is '
                    'locked (%s) (parent=%s)',
                    ntiid, missing_item.containerId)
        if item_parent is None:
            item_parent = package
        parents_questions = IQAssessmentItemContainer(item_parent)
        # pylint: disable=too-many-function-args
        parents_questions.append(missing_item)
        missing_item.__parent__ = item_parent


def transfer_transaction_records(removed):
    for item in removed:
        provided = iface_of_assessment(item)
        obj = component.queryUtility(provided, name=item.ntiid)
        if obj is not None:
            copy_transaction_history(item, obj)
        remove_transaction_history(item)


def update_assessment_items_when_modified(original, updated, event=None):
    update_key = needs_load_or_update(updated)
    if not update_key:
        return

    logger.info("Updating assessment items from modified content %s %s",
                updated, event)

    removed_items, locked_ntiids = on_content_package_removed(original, event,
                                                              force=False)
    logger.info("%s assessment item(s) have been removed from content %s",
                len(removed_items), original)

    registered = on_content_package_added(updated, event, key=update_key)
    logger.info("%s assessment item(s) have been registered for content %s",
                len(registered), updated)

    # Transfer locked items (now gone from content) to the new package.
    assesment_items = get_content_packages_assessment_items(updated)

    if locked_ntiids:
        transfer_locked_items_to_content_package(updated,
                                                 assesment_items,
                                                 locked_ntiids)

    # Transfer records
    transfer_transaction_records(removed_items)

    if len(assesment_items) < len(registered):
        raise AssertionError("[%s] Item(s) in content package %s are less that "
                             "in the registry %s" %
                             (updated.ntiid, len(assesment_items), len(registered)))


@component.adapter(IContentPackage, IObjectModifiedEvent)
def on_content_package_modified(package, event=None):
    if IEditableContentPackage.providedBy(package):
        return
    # The event may be an IContentPackageReplacedEvent, a subtype of the
    # modification event. In that case, because we are directly storing
    # some information on the instance object, we need to remove
    # from the OLD objects, and store on the NEW objects.
    # Because instance storage, we MUST always load things from the new packages;
    # it would be better to simply copy the assignment objects over and change
    # their parents (less DB churn) but its safer to do it the bulk-force way
    original = getattr(event, 'original', package)
    update_assessment_items_when_modified(original, package, event)
