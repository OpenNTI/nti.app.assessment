#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
does_not = is_not

import os
import simplejson

from zope import component

from nti.app.assessment.interfaces import IQEvaluations

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.contentlibrary.zodb import RenderableContentPackage

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestPacakgeViews(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    pkg_ntiid = u'tag:nextthought.com,2011-10:OU-HTML-CS1323_F_2015_Intro_to_Computer_Programming.introduction_to_computer_programming'

    def load_resource(self, resource):
        path = os.path.join(os.path.dirname(__file__), resource)
        with open(path, "r") as fp:
            return simplejson.load(fp)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_post_question(self):
        ntiid = u'tag:nextthought.com,2011-10:NTI-HTML-bleach_ichigo'
        package = RenderableContentPackage(title=u'Bleach',
                                           description=u'Manga bleach')
        package.ntiid = ntiid
        package.creator = self.default_username
        with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
            library = component.getUtility(IContentPackageLibrary)
            library.add(package, event=False)

        href = '/dataserver2/Library/%s/Evaluations' % ntiid
        data = self.load_resource("question.json")
        res = self.testapp.post_json(href, data, status=201)
        assert_that(res.json_body, has_key('ntiid'))
        q_ntiid = res.json_body['ntiid']

        with mock_dataserver.mock_db_trans(self.ds, site_name='platform.ou.edu'):
            package = find_object_with_ntiid(ntiid)
            evals = IQEvaluations(package)
            assert_that(evals, has_key(q_ntiid))
            assert_that(evals, has_length(is_(1)))

        href = '/dataserver2/Library/%s' % ntiid
        res = self.testapp.get(href, status=200)
        items_href = self.require_link_href_with_rel(res.json_body, "AssessmentItems")
        assignments_href = self.require_link_href_with_rel(res.json_body, "Assignments")

        res = self.testapp.get(items_href, status=200)
        assert_that(res.json_body, has_entry('Items', has_length(1)))

        res = self.testapp.get(assignments_href, status=200)
        assert_that(res.json_body, has_entry('Items', has_length(0)))

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_get_assignments(self):
        href = '/dataserver2/Library/%s' % self.pkg_ntiid
        res = self.testapp.get(href, status=200)
        assignments_href = self.require_link_href_with_rel(res.json_body, "Assignments")

        res = self.testapp.get(assignments_href, status=200)
        assert_that(res.json_body, has_entry('Total', is_(170)))
