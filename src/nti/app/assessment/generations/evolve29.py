#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 29

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.event import notify as event_notify

from nti.app.assessment.common.evaluations import get_evaluation_courses

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessmentDateContext
from nti.assessment.interfaces import QAssessmentDateContextModified

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.recorder.interfaces import IRecordable

from nti.site.hostpolicy import get_all_host_sites


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


def _is_obj_locked(context):
    return IRecordable.providedBy(context) and context.isLocked()


def _update_policy_dates(registry, seen):
    for ntiid, item in list(registry.getUtilitiesFor(IQAssignment)):
        if ntiid in seen:
            continue
        seen.add(ntiid)
        if not _is_obj_locked(item):
            continue
        courses = get_evaluation_courses(item)
        if courses:
            for course in courses:
                # Now copy dates from object to policy; this may cause
                # issues if we have updated dates in policy but not in object
                # (which will be wiped), but we don't think that case exists.
                dates = IQAssessmentDateContext(course)
                old_start = dates.of(item).available_for_submission_beginning
                old_end = dates.of(item).available_for_submission_ending
                new_start = item.available_for_submission_beginning
                new_end = item.available_for_submission_ending
                changed = False
                if new_start and new_start != old_start:
                    changed = True
                    dates.set(ntiid, 
                              'available_for_submission_beginning', 
                              new_start)
                    event_notify(
                        QAssessmentDateContextModified(dates, ntiid, 'available_for_submission_beginning')
                    )
                if new_end and new_end != old_end:
                    changed = True
                    dates.set(ntiid, 
                              'available_for_submission_ending',
                              new_end)
                    event_notify(
                        QAssessmentDateContextModified(dates, ntiid, 'available_for_submission_ending')
                    )
                if changed:
                    entry = ICourseCatalogEntry(course, None)
                    entry_ntiid = getattr(entry, 'ntiid', '')
                    title = getattr(item, 'title', '')
                    logger.info('Updating assignment dates in course policy (%s) (%s) (course=%s) (old_start=%s) (new_start=%s) (old_end=%s) (new_end=%s)',
                                ntiid, title, entry_ntiid, old_start, new_start, old_end, new_end)
        else:
            logger.warn('No courses found for assignment (%s)', ntiid)


def do_evolve(context, generation=generation):
    logger.info("Assessment evolution %s started", generation)

    setHooks()
    conn = context.connection
    ds_folder = conn.root()['nti.dataserver']

    mock_ds = MockDataserver()
    mock_ds.root = ds_folder
    component.provideUtility(mock_ds, IDataserver)

    with current_site(ds_folder):
        assert component.getSiteManager() == ds_folder.getSiteManager(), \
               "Hooks not installed?"

        # Load library
        library = component.queryUtility(IContentPackageLibrary)
        if library is not None:
            library.syncContentPackages()

        seen = set()
        for site in get_all_host_sites():
            with current_site(site):
                registry = component.getSiteManager()
                _update_policy_dates(registry, seen)

        seen.clear()

    component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
    logger.info('Assessment evolution %s done.', generation)


def evolve(context):
    """
    Evolve to generation 29 by moving assignment dates (only on locked/edited assignments)
    to all course assignment policies for that assignment.
    """
    do_evolve(context)
