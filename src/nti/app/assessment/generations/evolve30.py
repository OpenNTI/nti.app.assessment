#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 30

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from nti.app.assessment.common import get_courses
from nti.app.assessment.common import regrade_evaluation
from nti.app.assessment.common import evaluation_submissions
from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import get_evaluation_courses

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.coremetadata.interfaces import IRecordable

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.site.hostpolicy import get_host_site
from nti.site.hostpolicy import get_all_host_sites

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

@interface.implementer(IDataserver)
class MockDataserver(object):

	root = None

	def get_by_oid(self, oid, ignore_creator=False):
		resolver = component.queryUtility(IOIDResolver)
		if resolver is None:
			logger.warn("Using dataserver without a proper ISiteManager configuration.")
		else:
			return resolver.get_object_by_oid(oid, ignore_creator=ignore_creator)
		return None

def check_registry( registry, evaluation, site_name, entry_ntiid ):
	"""
	Check if registered object is same as given object; if not register
	given object.
	"""
	provided = iface_of_assessment(evaluation)
	registered = registry.queryUtility(provided, name=evaluation.ntiid)
	needs_regrade = False
	if registered is not None and registered != evaluation:
		logger.info( "[%s] Item does not match registry (%s), re-registering (course=%s)",
					 site_name, evaluation.ntiid, entry_ntiid )
		if IQuestion.providedBy( evaluation ):
			for part, registered_part in zip( evaluation.parts or (),
											  registered.parts or () ):
				if part.randomized != registered_part.randomized:
					needs_regrade = True
		# TODO: Remove intid?
		unregisterUtility(registry, provided=provided, name=evaluation.ntiid)
		registerUtility(registry, evaluation, provided=provided,
						name=evaluation.ntiid, event=False)
	return needs_regrade

def _is_obj_locked(context):
	return IRecordable.providedBy(context) and context.isLocked()

def _get_assignment_courses( assignment ):
	"""
	Get all courses and subinstances for our assignment.
	"""
	courses = get_evaluation_courses( assignment )
	result = set()
	for course in courses or ():
		all_courses = get_courses( course, subinstances=True )
		result.update( all_courses )
	return tuple( result )

def _update_registered_objects(site_registry, seen, site_name):
	"""
	Loop through all locked assignments making sure underlying
	question_sets and questions are the registered objects. If
	not register and regrade if randomized status is different.
	"""
	for ntiid, item in list(site_registry.getUtilitiesFor(IQAssignment)):
		if ntiid in seen:
			continue
		seen.add(ntiid)
		if not _is_obj_locked( item ):
			continue

		courses = _get_assignment_courses( item )
		if courses:
			needs_regrade = False
			# Arbitrary course for site registry and logging
			course = courses[0]
			course_site_name = get_resource_site_name(course)
			registry = get_host_site(course_site_name).getSiteManager()
			entry_ntiid = ICourseCatalogEntry( course ).ntiid
			for part in item.parts or ():
				question_set = part.question_set
				check_registry( registry, question_set, course_site_name, entry_ntiid )
				for question in question_set.questions or ():
					part_regrade = check_registry( registry, question,
												   course_site_name, entry_ntiid )
					if part_regrade:
						needs_regrade = True
			if needs_regrade:
				for course in courses:
					entry = ICourseCatalogEntry( course, None )
					entry_ntiid = getattr( entry, 'ntiid', '' )
					submissions = evaluation_submissions( item, course )
					submission_count = len( submissions or () )
					logger.info( "[%s] Regrading assessment (%s) (course=%s) (submission_count=%s)",
								 course_site_name, ntiid, entry_ntiid, submission_count )
					regrade_evaluation(item, course)
		else:
			logger.warn( '[%s] No courses found for assignment (%s)',
						 site_name, ntiid )

def do_evolve(context, generation=generation):
	logger.info("Assessment evolution %s started", generation);

	setHooks()
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	with current_site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		# Load library
		library = component.queryUtility(IContentPackageLibrary)
		if library is not None:
			library.syncContentPackages()

		seen = set()
		for site in get_all_host_sites():
			with current_site(site):
				site_name = site.__name__
				registry = component.getSiteManager()
				_update_registered_objects(registry, seen, site_name)

		seen.clear()

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 30 by looking for locked assignments and make sure the
	underlying questions and question sets are the items registered.
	"""
	do_evolve(context)

