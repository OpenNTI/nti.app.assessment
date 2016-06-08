#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generations for managing assesments.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 24

from zope.generations.generations import SchemaManager

from zope.intid.interfaces import IIntIds

from nti.app.assessment.index import install_evaluation_catalog
from nti.app.assessment.index import install_submission_catalog

class _AssessmentSchemaManager(SchemaManager):
	"""
	A schema manager that we can register as a utility in ZCML.
	"""
	def __init__(self):
		super(_AssessmentSchemaManager, self).__init__(
					generation=generation,
					minimum_generation=generation,
					package_name='nti.app.assessment.generations')

def evolve(context):
	install_catalog(context)

def install_catalog(context):
	conn = context.connection
	root = conn.root()
	dataserver_folder = root['nti.dataserver']
	lsm = dataserver_folder.getSiteManager()
	intids = lsm.getUtility(IIntIds)
	install_submission_catalog(dataserver_folder, intids)
	install_evaluation_catalog(dataserver_folder, intids)
