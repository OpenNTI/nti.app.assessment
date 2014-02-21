#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""


.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.testing.layers import GCLayerMixin
from nti.testing.layers import ZopeComponentLayer
from nti.testing.layers import ConfiguringLayerMixin
from nti.testing.layers import find_test

from nti.dataserver.tests.mock_dataserver import DSInjectorMixin
import zope.testing.cleanup


class SharedConfiguringTestLayer(ZopeComponentLayer,
								 GCLayerMixin,
								 ConfiguringLayerMixin,
								 DSInjectorMixin):
	set_up_packages = ('nti.appserver', 'nti.app.assessment')

	@classmethod
	def setUp(cls):
		cls.setUpPackages()

	@classmethod
	def tearDown(cls):
		cls.tearDownPackages()
		zope.testing.cleanup.cleanUp()

	@classmethod
	def testSetUp(cls, test=None):
		test = test or find_test()
		cls.setUpTestDS(test)

import unittest
class AssessmentLayerTest(unittest.TestCase):
	layer = SharedConfiguringTestLayer
