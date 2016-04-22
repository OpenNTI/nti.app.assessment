#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 10

from zope import component
from zope import interface

from zope.component.hooks import site as current_site

from zope.container.interfaces import IContainer

from nti.app.assessment.interfaces import IUsersCourseInquiries
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories
from nti.app.assessment.interfaces import IUsersCourseAssignmentSavepoints
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.contenttypes.courses.interfaces import ICourseCatalog 
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.dataserver.users import User

from nti.site.hostpolicy import get_all_host_sites

CONTAINER_INTERFACES = (IUsersCourseInquiries,
						IUsersCourseAssignmentHistories,
						IUsersCourseAssignmentSavepoints,
						IUsersCourseAssignmentMetadataContainer)

def clean_course(course):
	for iface in CONTAINER_INTERFACES:
		container = iface(course)
		for username, item in tuple(container.items()): # mutating
			if not username or User.get_user(username) is None:
				if IContainer.providedBy(item):
					item.clear()
				del container[username]

def clean_sites():
	for site in get_all_host_sites():
		with current_site(site):
			catalog = component.getUtility(ICourseCatalog)
			for entry in catalog.iterCatalogEntries():
				course = ICourseInstance(entry)
				clean_course(course)

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

def do_evolve(context, generation=generation):
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']

	mock_ds = MockDataserver()
	mock_ds.root = ds_folder
	component.provideUtility(mock_ds, IDataserver)

	with current_site(ds_folder):
		assert	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"
		clean_sites()
	
	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('contenttypes.courses evolution %s done.', generation)
	
def evolve(context):
	"""
	Evolve to generation 10 by removing data for invalid users
	"""
	do_evolve(context, generation)
