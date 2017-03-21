#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import has_key
from hamcrest import assert_that

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests.mock_dataserver import mock_db_trans


class TestFunctionalInstall(ApplicationLayerTest):

    @WithSharedApplicationMockDS
    def test_installed(self):
        with mock_db_trans(self.ds) as conn:
            root = conn.root()
            generations = root['zope.generations']
            assert_that(generations, has_key('nti.dataserver-app-assessment'))
