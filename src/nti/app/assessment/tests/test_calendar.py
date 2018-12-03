#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

import datetime

from hamcrest import is_
from hamcrest import calling
from hamcrest import raises
from hamcrest import not_none
from hamcrest import assert_that
from hamcrest import has_entries
from hamcrest import has_length
from hamcrest import same_instance
from hamcrest import has_properties

from zope import component

from zope.intid.interfaces import IIntIds

from nti.assessment.assignment import QAssignment

from nti.app.assessment.tests import AssessmentLayerTest

from nti.app.assessment.calendar import AssignmentCalendarEvent
from nti.app.assessment.calendar import AssignmentCalendarDynamicEventProvider

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollmentManager

from nti.dataserver.users.users import User

from nti.dataserver.tests import mock_dataserver

from nti.externalization import internalization

from nti.externalization.externalization import toExternalObject

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.ntiids.oids import to_external_ntiid_oid


class TestExternalization(AssessmentLayerTest):

    def testAssignmentCalendarEvent(self):
        assignment = QAssignment(title=u'a')
        obj =  AssignmentCalendarEvent(title=u'reading',
                                       description=u'this is',
                                       location=u'oklahoma',
                                       assignment=assignment)
        external = toExternalObject(obj)
        assert_that(external, has_entries({'title': 'reading',
                                           'description': 'this is',
                                           'location': 'oklahoma',
                                           'start_time': not_none(),
                                           'Class': 'AssignmentCalendarEvent',
                                           'MimeType': 'application/vnd.nextthought.assessment.assignmentcalendarevent'}))
        assert_that(external['assignment'], has_entries({'title': u'a'}))

        # Should not be created externally.
        factory = internalization.find_factory_for(external)
        assert_that(factory, is_(None))


class TestCourseCalendarDynamicEventProvider(ApplicationLayerTest):

    layer = InstructedCourseApplicationTestLayer

    default_origin = 'http://janux.ou.edu'

    entry_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'

    def _get_course_oid(self, entry_ntiid=None):
        entry_ntiid = entry_ntiid if entry_ntiid else self.entry_ntiid
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(entry_ntiid)
            course = ICourseInstance(entry)
            return to_external_ntiid_oid(course)

    def _post_assignment(self, course_oid, title=u'one', description=u'it is ok', username=u'admintest@nextthought.com'):
        url = '/dataserver2/Objects/%s/CourseEvaluations' % course_oid
        params = {
            "MimeType":"application/vnd.nextthought.assessment.assignment",
            "content":description,
            "title": title
        }
        return self.testapp.post_json(url, params, status=201, extra_environ=self._make_extra_environ(username=username)).json_body

    def _publish_assignment(self, assignment_ntiid, username=u'admintest@nextthought.com'):
        href = '/dataserver2/NTIIDs/%s/@@publish' % assignment_ntiid
        return self.testapp.post_json(href, status=200, extra_environ=self._make_extra_environ(username=username)).json_body

    @WithSharedApplicationMockDS(testapp=True, users=(u'test001', u'admintest@nextthought.com'))
    def test_course_calendar_dynamic_event_provider(self):
        admin = u'admintest@nextthought.com'
        username = u'test001'
        course_oid = self._get_course_oid()

        res = self._post_assignment(course_oid)
        assignment_ntiid = res['NTIID']

        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            entry = find_object_with_ntiid(self.entry_ntiid)
            course = ICourseInstance(entry)

            user = User.get_user(username)
            enrollment_manager = ICourseEnrollmentManager(course)
            enrollment_manager.enroll(user)

            provider = AssignmentCalendarDynamicEventProvider(user, course)
            events = provider.iter_events()
            assert_that(events, has_length(41))

        self._publish_assignment(assignment_ntiid)
        with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
            events = provider.iter_events()
            assert_that(events, has_length(41))

            assignment = find_object_with_ntiid(assignment_ntiid)
            assignment.available_for_submission_ending = datetime.datetime.utcfromtimestamp(1539993600)

            events = provider.iter_events()
            assert_that(events, has_length(42))

            event = [x for x in provider.iter_events() if x.assignment.ntiid == assignment_ntiid][0]
            assert_that(event, has_properties({'title': 'one', 'description': 'it is ok'}))
            assert_that(event.__parent__, is_(None))
            assert_that(event.__name__, is_(None))
            assert_that(event.end_time, is_(None))
            assert_that(event.start_time.strftime('%Y-%m-%d %H:%M:%S'), is_('2018-10-20 00:00:00'))
            assert_that(event.assignment, same_instance(assignment))

            # no intid
            intids = component.getUtility(IIntIds)
            assert_that(intids.queryId(event), is_(None))
