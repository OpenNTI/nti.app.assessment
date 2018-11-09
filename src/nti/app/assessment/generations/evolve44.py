#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 27.

.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

generation = 44

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks

from zope.container.interfaces import INameChooser

from zope.intid.interfaces import IIntIds

from nti.app.assessment.history import UsersCourseAssignmentHistoryItemContainer

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemContainer

from nti.app.assessment.metadata import UsersCourseAssignmentAttemptMetadataItem

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.coremetadata.interfaces import IUser

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.dataserver.metadata.index import get_metadata_catalog

from nti.dataserver.users import User

from nti.traversal.traversal import find_interface

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IDataserver)
class MockDataserver(object):

    root = None

    def get_by_oid(self, oid, ignore_creator=False):
        resolver = component.queryUtility(IOIDResolver)
        if resolver is None:
            logger.warn("Using dataserver without a proper ISiteManager.")
        else:
            return resolver.get_object_by_oid(oid, ignore_creator=ignore_creator)
        return None


def get_user(obj):
    result = obj.creator
    if not IUser.providedBy(result):
        result = User.get_user(result)
    assert IUser.providedBy(result), obj.creator
    return result


def legacy_seed(user, intids):
    return bytes(intids.getId(user))


def create_meta_attempt(user, item, intids):
    # XXX: Do we need to migrate the old timed assignment meta?
    course = find_interface(item, ICourseInstance)
    user_meta = component.queryMultiAdapter((course, user),
                                            IUsersCourseAssignmentAttemptMetadata)
    # This part cannot be idempotent
    item_container = user_meta.get_or_create(item.assignmentId)
    if len(item_container) < 1:
        # Only do this if this is our only attempt
        attempt = UsersCourseAssignmentAttemptMetadataItem()
        attempt.containerId = item.assignmentId
        attempt.Seed = legacy_seed(user, intids)
        # All floats (int duration)
        # Legacy submissions will not have durations
        attempt.Duration = duration = getattr(item.Submission, 'CreatorRecordedEffortDuration', -1)
        attempt.StartTime = item.createdTime - duration if duration > 0 else 0
        attempt.SubmitTime = item.createdTime
        attempt.HistoryItem = item
        item_container.add_attempt(attempt)


def do_evolve(context, generation=generation):
    logger.info("Assessment evolution %s started", generation)

    setHooks()
    conn = context.connection
    ds_folder = conn.root()['nti.dataserver']
    lsm = ds_folder.getSiteManager()

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)
    intids = lsm.getUtility(IIntIds)

    with site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        total = 0
        metadata_catalog = get_metadata_catalog()
        index = metadata_catalog['mimeType']

        MIME_TYPES = ('application/vnd.nextthought.assessment.userscourseassignmenthistoryitem',)
        item_intids = index.apply({'any_of': MIME_TYPES})
        for doc_id in item_intids or ():
            item = intids.queryObject(doc_id)
            if IUsersCourseAssignmentHistoryItem.providedBy(item):
                user_history = item.__parent__
                if user_history is None:
                    logger.warn('History item without lineage (%s)', item)
                    continue
                user = get_user(item)
                create_meta_attempt(user, item, intids)
                if IUsersCourseAssignmentHistoryItemContainer.providedBy(user_history):
                    # Idempotent
                    continue
                total += 1
                if total % 100 == 0:
                    logger.info('%s history item containers added', total)

                try:
                    item.Feedback._order
                except AttributeError:
                    # seen in prod, a container without an `_order` attr
                    logger.info('Invalid feedback container (%s) (%s)', item, item.Feedback)
                    delattr(item, 'Feedback')

                # Of course we should only have one submission per assignment
                # at the time of this migration.
                # XXX: Must use __name__ here since AssignmentId is derived incorrectly
                # until we update lineage.
                submission_container = user_history._delitemf(item.__name__, event=False)
                if not IUsersCourseAssignmentHistoryItemContainer.providedBy(submission_container):
                    submission_container = UsersCourseAssignmentHistoryItemContainer()
                user_history[item.__name__] = submission_container
                assert submission_container.__parent__ is not None
                chooser = INameChooser(submission_container)
                key = chooser.chooseName('', item)
                submission_container[key] = item
                assert item.__parent__ is submission_container

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done; %s items(s) updated',
                generation, total)


def evolve(context):
    """
    Evolve to generation 44 to put all IUsersCourseAssignmentHistoryItem
    objects in IUsersCourseAssignmentHistoryItemContainer objects for
    multiple submissions. Also update our metadata structures.
    """
    do_evolve(context)
