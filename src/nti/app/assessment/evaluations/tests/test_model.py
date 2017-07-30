#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
does_not = is_not

from nti.testing.matchers import validly_provides
from nti.testing.matchers import verifiably_provides

from zope import component

from zope.intid.interfaces import IIntIds

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.assessment.evaluations.model import LegacyContentPackageEvaluations

from nti.assessment.question import QQuestion

from nti.contentlibrary.interfaces import IContentPackage

from nti.contentlibrary.zodb import RenderableContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.courses import CourseInstance

from nti.traversal.traversal import find_interface

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestModel(ApplicationLayerTest):

    def _test_container(self, context, package=True):
        intids = component.getUtility(IIntIds)
        if package:
            evals = LegacyContentPackageEvaluations(context)
        else:
            evals = IQEvaluations(context, None)
            assert_that(evals, is_not(none()))

        assert_that(evals, validly_provides(IQEvaluations))
        assert_that(evals, verifiably_provides(IQEvaluations))
        assert_that(evals,
                    has_property('__parent__', is_(context)))
        if package:
            assert_that(evals,
                        has_property('__name__', is_('Evaluations')))
        assert_that(evals, has_length(0))

        ntiid = u'tag:nextthought.com,2011-10:OU-NAQ-Q1'
        question = QQuestion()
        question.ntiid = ntiid
        assert_that(evals, does_not(has_key(ntiid)))

        evals[ntiid] = question
        assert_that(evals, has_length(1))
        assert_that(evals, has_entry(ntiid, is_(question)))

        doc_id = intids.queryId(question)
        assert_that(doc_id, is_not(none()))
        assert_that(question, has_property('__name__', ntiid))
        if package:
            parent = find_interface(question, IContentPackage, strict=False)
            assert_that(parent, is_not(none()))
        else:
            parent = find_interface(question, ICourseInstance, strict=False)
            assert_that(parent, is_not(none()))

        assert_that(list(evals), is_([ntiid]))
        assert_that(list(evals.keys()), is_([ntiid]))
        assert_that(list(evals.values()), is_([question]))
        assert_that(list(evals.items()), is_([(ntiid, question)]))

        replacement = QQuestion()
        replacement.ntiid = ntiid
        evals.replace(question, replacement)
        assert_that(evals, has_length(1))

        doc_id = intids.queryId(question)
        assert_that(doc_id, is_(none()))
        assert_that(question, has_property('ntiid', is_(ntiid)))
        assert_that(question,
                    has_property('__parent__', is_(none())))

        doc_id = intids.queryId(replacement)
        assert_that(doc_id, is_not(none()))
        assert_that(evals, has_entry(ntiid, is_(replacement)))
        assert_that(replacement,
                    has_property('__parent__', is_not(none())))

        del evals[ntiid]
        assert_that(evals, has_length(0))
        assert_that(evals, does_not(has_key(ntiid)))

        doc_id = intids.queryId(replacement)
        assert_that(doc_id, is_(none()))
        assert_that(replacement, has_property('ntiid', is_(ntiid)))
        assert_that(replacement,
                    has_property('__parent__', is_(none())))

    @WithSharedApplicationMockDS(testapp=False, users=False)
    def test_evaluations(self):

        with mock_dataserver.mock_db_trans(self.ds) as conn:
            package = RenderableContentPackage()
            conn.add(package)
            self._test_container(package)

        with mock_dataserver.mock_db_trans(self.ds) as conn:
            course = CourseInstance()
            conn.add(course)
            self._test_container(course, False)
