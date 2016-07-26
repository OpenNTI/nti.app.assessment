#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 22

from zope import component
from zope import interface

from zope.component.hooks import site
from zope.component.hooks import setHooks
from zope.component.hooks import site as current_site

from zope.interface.interfaces import IMethod

from ZODB.interfaces import IConnection

from persistent.list import PersistentList

from nti.assessment.interfaces import IQPart
from nti.assessment.interfaces import IQuestion 

from nti.assessment.parts import QMatchingPart
from nti.assessment.parts import QOrderingPart
from nti.assessment.parts import QMultipleChoicePart
from nti.assessment.parts import QMultipleChoiceMultipleAnswerPart

from nti.assessment.randomized.parts import QRandomizedMatchingPart
from nti.assessment.randomized.parts import QRandomizedOrderingPart
from nti.assessment.randomized.parts import QRandomizedMultipleChoicePart
from nti.assessment.randomized.parts import QRandomizedMultipleChoiceMultipleAnswerPart

from nti.dataserver.interfaces import IDataserver
from nti.dataserver.interfaces import IOIDResolver

from nti.externalization.proxy import removeAllProxies

from nti.schema.interfaces import find_most_derived_interface

from nti.site.hostpolicy import get_all_host_sites

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

def _process_items(registry, seen):
	for name, item in list(registry.getUtilitiesFor(IQuestion)):
		if name in seen:
			continue
		seen.add(name)
		modified = False
		parts = PersistentList()
		question = removeAllProxies(item)
		for part in question.parts or ():
			if isinstance(part, QRandomizedMatchingPart):
				factory = QMatchingPart
			elif isinstance(part, QRandomizedOrderingPart):
				factory = QOrderingPart
			elif isinstance(part, QRandomizedMultipleChoicePart):
				factory = QMultipleChoicePart
			elif isinstance(part, QRandomizedMultipleChoiceMultipleAnswerPart):
				factory = QMultipleChoiceMultipleAnswerPart
			else:
				factory = None

			if factory is not None:
				modified = True
				new_part = factory()
				parts.append(new_part)
				schema = find_most_derived_interface(part, IQPart)
				for k, v in schema.namesAndDescriptions(all=True):
					if not IMethod.providedBy(v):
						value = getattr(part, k, None)
						setattr(new_part, k, value)
				if IConnection(part, None) is not None:
					connection = IConnection(question)
					connection.add(new_part)
				# mark randomized
				new_part.randomized = True
				new_part.__parent__ = question  # set lineage
				# ground
				part.__parent__ = None
			else:
				parts.append(part)

		if modified:
			question.parts = parts
			question._p_changed = True
			logger.info("Question %s updated", name)

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

		seen = set()
		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()
				_process_items(registry, seen)

	component.getGlobalSiteManager().unregisterUtility(mock_ds, IDataserver)
	logger.info('Assessment evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 22 by updating the objects of randomzied parts
	"""
	do_evolve(context)
