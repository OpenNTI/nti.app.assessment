#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

# pylint: disable=protected-access,too-many-public-methods

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_key
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import assert_that
from hamcrest import has_property
from hamcrest import contains_string

from nti.testing.matchers import validly_provides

import time
import weakref

from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadataContainer

from nti.app.assessment.metadata import UsersCourseAssignmentMetadata
from nti.app.assessment.metadata import UsersCourseAssignmentMetadataItem
from nti.app.assessment.metadata import UsersCourseAssignmentMetadataContainer

from nti.app.assessment.tests import AssessmentLayerTest

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.tests.mock_dataserver import WithMockDSTrans

from nti.dataserver.users.users import User

from nti.ntiids.ntiids import find_object_with_ntiid


class TestMetadata(AssessmentLayerTest):

    @WithMockDSTrans
    def test_provides(self):
        container = UsersCourseAssignmentMetadataContainer()
        metadata = UsersCourseAssignmentMetadata()
        metadata.__parent__ = container
        # Set an owner; use a python wref instead of the default
        # adapter to wref as it requires an intid utility
        user = User.create_user(username=u'sjohnson@nextthought.com')
        metadata.owner = weakref.ref(user)
        item = UsersCourseAssignmentMetadataItem(StartTime=100.0)
        item.creator = u'foo'
        item.__parent__ = metadata
        assert_that(item,
                    validly_provides(IUsersCourseAssignmentMetadataItem))

        assert_that(metadata,
                    validly_provides(IUsersCourseAssignmentMetadata))

        assert_that(IUser(item), is_(metadata.owner))
        assert_that(IUser(metadata), is_(metadata.owner))

    @WithMockDSTrans
    def test_record(self):
        connection = mock_dataserver.current_transaction
        metadata = UsersCourseAssignmentMetadata()
        connection.add(metadata)
        item = UsersCourseAssignmentMetadataItem()
        item.StartTime = time.time()
        metadata.append(u"foo", item)

        assert_that(item, has_property('StartTime', is_not(none())))
        assert_that(item, has_property('__name__', is_('foo')))
        assert_that(item.__parent__, is_(metadata))
        assert_that(metadata, has_length(1))

        metadata.remove('foo')
        assert_that(metadata, has_length(0))

    @WithMockDSTrans
    def test_get_or_create(self):
        connection = mock_dataserver.current_transaction
        metadata = UsersCourseAssignmentMetadata()
        connection.add(metadata)
        item = metadata.get_or_create(u'foo', 1.0)
        assert_that(item, is_not(none()))
        assert_that(item, has_property('StartTime', is_(1.0)))
        item = metadata.get_or_create('foo', 100.0)
        assert_that(item, has_property('StartTime', is_(1.0)))


import fudge
from six.moves.urllib_parse import unquote

from nti.app.assessment.tests import RegisterAssignmentLayerMixin
from nti.app.assessment.tests import RegisterAssignmentsForEveryoneLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

COURSE_NTIID = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
COURSE_URL = u'/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice'


class TestMetadataViews(RegisterAssignmentLayerMixin, ApplicationLayerTest):

    layer = RegisterAssignmentsForEveryoneLayer

    features = ('assignments_for_everyone',)

    default_origin = 'http://janux.ou.edu'
    default_username = u'outest75'

    @WithSharedApplicationMockDS(users=(u'outest5',), testapp=True, default_authenticate=True)
    def test_fetching_entire_assignment_metadata_collection(self):

        outest_environ = self._make_extra_environ(username='outest5')
        outest_environ.update({'HTTP_ORIGIN': 'http://janux.ou.edu'})

        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)

        default_enrollment_metadata_link = self.require_link_href_with_rel(res.json_body, 'AssignmentAttemptMetadata')

        expected = ('/dataserver2/users/' +
                    self.default_username +
                    '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/AssignmentAttemptMetadata/' +
                    self.default_username)
        assert_that(unquote(default_enrollment_metadata_link),
                    is_(unquote(expected)))

        res = self.testapp.post_json('/dataserver2/users/outest5/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201,
                                     extra_environ=outest_environ)

        user2_enrollment_history_link = self.require_link_href_with_rel(res.json_body, 'AssignmentAttemptMetadata')

        # each can fetch his own
        self.testapp.get(default_enrollment_metadata_link)
        self.testapp.get(user2_enrollment_history_link,
                         extra_environ=outest_environ)

        # but they can't get each others
        self.testapp.get(default_enrollment_metadata_link,
                         extra_environ=outest_environ,
                         status=403)
        self.testapp.get(user2_enrollment_history_link, status=403)

    def _check_metadata(self, res, metadata_link=None):
        assert_that(res.status_int, is_(201))
        assert_that(res.json_body,
                	has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
        assert_that(res.json_body,
                    has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))
        assert_that(res.json_body, has_entry(StandardExternalFields.MIMETYPE,
                                             'application/vnd.nextthought.assessment.userscourseassignmentattemptmetadataitem'))

        assert_that(res.json_body, has_entry('href', is_not(none())))
        assert_that(res.json_body, has_key('NTIID'))
        assert_that(res.json_body, has_entry('StartTime', is_not(none())))
        assert_that(res.json_body,
                    has_entry('ContainerId', self.assignment_id))
        assert_that(res.json_body,
                    has_entry(StandardExternalFields.CREATED_TIME, is_(float)))
        assert_that(res.json_body,
                    has_entry(StandardExternalFields.LAST_MODIFIED, is_(float)))

        if metadata_link:
            metadata_res = self.testapp.get(metadata_link)
            assert_that(metadata_res.json_body,
                        has_entry('href', contains_string(unquote(metadata_link))))
            assert_that(metadata_res.json_body,
                        has_entry('Items', has_length(1)))

            items = list(metadata_res.json_body['Items'].values())
            assert_that(items[0], has_key('href'))
        else:
            self._fetch_user_url('/Courses/EnrolledCourses/CLC3403/AssignmentAttemptMetadata' +
                                 self.default_username, status=404)
        return res.json_body

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_metadata(self, fake_active):
        fake_active.is_callable().returns(True)

        item = UsersCourseAssignmentMetadataItem(StartTime=time.time())
        ext_obj = to_external_object(item)
        assert_that(ext_obj,
                    has_entry('MimeType', 'application/vnd.nextthought.assessment.userscourseassignmentattemptmetadataitem'))

        # Make sure we're enrolled
        res = self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                                     COURSE_NTIID,
                                     status=201)

        course_res = self.testapp.get(COURSE_URL).json_body
        enrollment_metadata_link = self.require_link_href_with_rel(res.json_body, 'AssignmentAttemptMetadata')
        course_metadata_link = self.require_link_href_with_rel(course_res, 'AssignmentAttemptMetadata')

        expected = ('/dataserver2/users/' +
                    self.default_username +
                    '/Courses/EnrolledCourses/tag%3Anextthought.com%2C2011-10%3ANTI-CourseInfo-Fall2013_CLC3403_LawAndJustice/AssignmentAttemptMetadata/' +
                    self.default_username)
        assert_that(unquote(enrollment_metadata_link),
                    is_(unquote(expected)))

        expected = ('/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2013/CLC3403_LawAndJustice/AssignmentAttemptMetadata/' +
                    self.default_username)
        assert_that(unquote(course_metadata_link),
                    is_(unquote(expected)))

        # Both links are equivalent and work; and both are empty before I
        # submit
        for link in course_metadata_link, enrollment_metadata_link:
            metadata_res = self.testapp.get(link)
            assert_that(metadata_res.json_body,
                        has_entry('Items', has_length(0)))

        href = '/dataserver2/Objects/' + self.assignment_id + '/Metadata'
        self.testapp.get(href, status=404)

        res = self.testapp.post_json(href, ext_obj)
        metadata_item_href = res.json_body['href']
        assert_that(metadata_item_href, is_not(none()))

        meta_body = self._check_metadata(res, enrollment_metadata_link)

        res = self.testapp.get(metadata_item_href)
        assert_that(res.json_body, has_entry('href', is_not(none())))

        res = self.testapp.get(href)
        assert_that(res.json_body, has_entry('href', is_not(none())))

        # Both metadata links are equivalent and work
        for link in course_metadata_link, enrollment_metadata_link:
            metadata_res = self.testapp.get(link)
            assert_that(metadata_res.json_body,
                        has_entry('Items', has_length(1)))
            assert_that(metadata_res.json_body,
                        has_entry('Items', has_key(self.assignment_id)))

        # simply adding get us to an item
        href = metadata_res.json_body['href'] + '/' + self.assignment_id
        res = self.testapp.get(href)
        assert_that(res.json_body, has_entry('href', is_not(none())))

        # we cannnot delete
        self.testapp.delete(metadata_item_href, status=403)
        self.testapp.get(metadata_item_href, status=200)

        # Put
        ext_obj['StartTime'] = 0  # Ignored
        res = self.testapp.put_json(metadata_item_href, ext_obj, status=200)
        assert_that(res.json_body,
                    has_entry('StartTime', is_(meta_body['StartTime'])))

        # The instructor can delete our metadada
        instructor_environ = self._make_extra_environ(username='harp4162')
        self.testapp.delete(metadata_item_href,
                            extra_environ=instructor_environ, status=204)

    @WithSharedApplicationMockDS(users=('outest5',), testapp=True, default_authenticate=True)
    @fudge.patch('nti.contenttypes.courses.catalog.CourseCatalogEntry.isCourseCurrentlyActive')
    def test_metadata_commence(self, fake_active):
        fake_active.is_callable().returns(True)

        # Make sure we're enrolled
        self.testapp.post_json('/dataserver2/users/' + self.default_username + '/Courses/EnrolledCourses',
                               COURSE_NTIID,
                               status=201)

        href = '/dataserver2/Objects/' + self.assignment_id + '/Commence'
        self.testapp.get(href, status=404)

        res = self.testapp.post_json(href)
        assert_that(res.json_body, has_entry('Class', is_('Assignment')))

        href = '/dataserver2/Objects/' + self.assignment_id + '/StartTime'
        res = self.testapp.get(href, status=200)
        assert_that(res.json_body, has_entry('StartTime', is_not(none())))

        with mock_dataserver.mock_db_trans(self.ds, site_name='janux.ou.edu'):
            course = ICourseInstance(find_object_with_ntiid(COURSE_NTIID))
            container = IUsersCourseAssignmentMetadataContainer(course)
            print(len(container))
            container.clear()
            assert_that(container, has_length(0))
