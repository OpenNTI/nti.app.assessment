#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_property
from hamcrest import assert_that
does_not = is_not

from zope import component

from zope.intid.interfaces import IIntIds

from nti.app.assessment.generations import evolve40

from nti.assessment.assignment import QAssignment

from nti.assessment.interfaces import IQAssignment

from nti.site.utils import registerUtility

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver


class TestEvolve40(ApplicationLayerTest):

    default_origin = 'http://janux.ou.edu'

    @WithSharedApplicationMockDS(users=False, testapp=False)
    def test_process_site(self):
        ntiid = u'tag:nextthought.com,2011-10:OU-NAQ-quiz1'
        with mock_dataserver.mock_db_trans(self.ds, 'platform.ou.edu'):
            evaluation = QAssignment()
            evaluation.__dict__['__name__'] = ntiid
            evaluation.signature = u'xyz'
            intids = component.getUtility(IIntIds)
            intids.register(evaluation)
            registerUtility(component.getSiteManager(), evaluation,
                            provided=IQAssignment,
                            name=ntiid, event=False)

        with mock_dataserver.mock_db_trans(self.ds, 'platform.ou.edu'):
            seen = set()
            intids = component.getUtility(IIntIds)
            evolve40.process_site(intids, seen)
            evaluation = component.getUtility(IQAssignment, name=ntiid)
            assert_that(evaluation.__dict__,
                        does_not(has_key('__name__')))
            assert_that(evaluation.__dict__,
                        does_not(has_key('signature')))
            assert_that(evaluation,
                        has_property('ntiid', is_(ntiid)))
            assert_that(evaluation,
                        has_property('__name__', is_(ntiid)))
