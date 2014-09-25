#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
generation 3.

.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 3

from zope import component
from zope.component.hooks import site, setHooks

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.site.hostpolicy import run_job_in_all_host_sites

from ..interfaces import IUsersCourseAssignmentHistory
from ..interfaces import IUsersCourseAssignmentSavepoint

def remove_savepoints():
	catalog = component.getUtility(ICourseCatalog)
	for entry in catalog.iterCatalogEntries():
		course = ICourseInstance(entry)
		enrollments = ICourseEnrollments(course)
		for record in enrollments.iter_enrollments():
			principal = record.Principal
			history = component.queryMultiAdapter((course, principal), 
												  IUsersCourseAssignmentHistory)
			savepoint = component.queryMultiAdapter((course, principal), 
												    IUsersCourseAssignmentSavepoint)
			if not savepoint or not history:
				continue
			for assignmentId in history.keys():
				if assignmentId in savepoint:
					del savepoint[assignmentId]
			
def do_evolve(context):
	setHooks()
	conn = context.connection
	root = conn.root()
	ds_folder = root['nti.dataserver']

	logger.info('Evolution %s started', generation)
	
	with site(ds_folder):
		assert	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		run_job_in_all_host_sites(remove_savepoints)
	
		logger.info('Evolution %s done', generation)

def evolve(context):
	"""
	Evolve to generation 3 by removing savepoint for already submitted item(s)
	"""
	do_evolve(context)
