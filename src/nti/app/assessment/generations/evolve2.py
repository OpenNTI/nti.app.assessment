#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 2.

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 2

from zope import component
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.annotation.interfaces import IAnnotations
from zope.traversing.interfaces import IEtcNamespace

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.site.interfaces import IHostPolicyFolder

from ..savepoint import BASE_KEY
from ..savepoint import _user_savepoint_course_key

def migrate_course_savepoints(entry, users):
	course = ICourseInstance(entry)
	key = _user_savepoint_course_key(course)
	course_annotations = IAnnotations(course, {})
	
	savepoints = course_annotations.get(BASE_KEY, {})
	logger.info("Processing %s savepoints", len(savepoints))
	
	for username, savepoint in savepoints.items():
		user = users.get(username)
		if not user:
			continue
				
		# set in user annotation
		user_annotations = IAnnotations(user)
		user_annotations[key] = savepoint
		
		# reparent save point
		savepoint.__name__ = key
		savepoint.__parent__ = user	
	
		# remove old owner reference
		if getattr(savepoint, '_owner_ref', None) is not None:
			delattr(savepoint, '_owner_ref')

	# remove
	if hasattr(savepoints, '__parent__'):
		savepoints.__parent__ = None
	course_annotations.pop(BASE_KEY, None)
	
def do_evolve(context):
	setHooks()
	conn = context.connection
	root = conn.root()
	ds_folder = root['nti.dataserver']

	logger.info('Generation %s started', generation)

	with current_site(ds_folder):
		assert 	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		users = ds_folder['users']
		sites = component.getUtility(IEtcNamespace, name='hostsites')
		
		for name, site in sites.items():
			if not IHostPolicyFolder.providedBy(site):
				continue
			logger.info("Processing site %s", name)
			with current_site(site):
				catalog = component.getUtility(ICourseCatalog)
				for entry in catalog.iterCatalogEntries():
					logger.info("Processing course %s", entry.ntiid)
					migrate_course_savepoints(entry, users)
					
	logger.info('Generation %s completed', generation)

def evolve(context):
	"""
	Evolve to generation 2 by removing moving save points from course to user
	"""
	do_evolve(context)
