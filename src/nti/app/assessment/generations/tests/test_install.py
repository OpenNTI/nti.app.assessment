#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import has_key
from hamcrest import assert_that

from nti.dataserver.tests import mock_dataserver
from nti.dataserver.tests.mock_dataserver import WithMockDSTrans
from nti.dataserver.tests.mock_dataserver import DataserverLayerTest

class TestFunctionalInstall(DataserverLayerTest):

	@WithMockDSTrans
	def test_installed(self):
		conn = mock_dataserver.current_transaction
		root = conn.root()
		generations = root['zope.generations']
		assert_that( generations, has_key('nti.app.assessment.generations'))
