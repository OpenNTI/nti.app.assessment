#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import all_of
from hamcrest import has_key
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import assert_that
does_not = is_not

import fudge

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.app.assessment.tests import AssessmentLayerTest

from nti.app.products.courseware.tests import PersistentInstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.externalization.tests import externalizes

GIF_DATAURL = b'data:image/gif;base64,R0lGODlhCwALAIAAAAAA3pn/ZiH5BAEAAAEALAAAAAALAAsAAAIUhA+hkcuO4lmNVindo7qyrIXiGBYAOw=='


class TestDecorators(AssessmentLayerTest):

    def test_upload_file(self):
        ext_obj = {
            'MimeType': 'application/vnd.nextthought.assessment.uploadedfile',
            'value': GIF_DATAURL,
            'filename': u'c:\dir\file.gif',
            'name': u'ichigo'
        }
        assert_that(find_factory_for(ext_obj), is_(not_none()))
        internal = find_factory_for(ext_obj)()
        update_from_external_object(internal, ext_obj, require_updater=True)
        assert_that(internal, externalizes(all_of(has_key('FileMimeType'),
                                                  has_key('filename'),
                                                  has_key('name'),
                                                  has_entry('url', none()),
                                                  has_key('CreatedTime'),
                                                  has_key('Last Modified'))))
        # But we have no URL because we're not in a connection anywhere

    def test_file_upload2(self):
        # Temporary workaround for iPad bug.
        ext_obj = {
            'MimeType': 'application/vnd.nextthought.assessment.quploadedfile',
            'value': GIF_DATAURL,
            'filename': u'c:\dir\file.gif',
            'name': u'ichigo'
        }

        assert_that(find_factory_for(ext_obj), is_(not_none()))
        internal = find_factory_for(ext_obj)()
        update_from_external_object(internal, ext_obj, require_updater=True)
        assert_that(internal, externalizes(all_of(has_key('FileMimeType'),
                                                  has_key('filename'),
                                                  has_key('name'),
                                                  has_entry('url', none()),
                                                  has_key('CreatedTime'),
                                                  has_key('Last Modified'))))


class TestCoursePreviewExternalization(ApplicationLayerTest):
    """
    Validate courses in preview mode hide features from enrolled students,
    but still expose them for admins.
    """

    layer = PersistentInstructedCourseApplicationTestLayer

    default_origin = 'http://platform.ou.edu'

    course_href = '/dataserver2/Objects/tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
    course_ntiid = None

    enrolled_courses_href = '/dataserver2/users/test_student/Courses/EnrolledCourses'
    enrollment_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

    def _do_enroll(self, environ):
        self.testapp.post_json(self.enrolled_courses_href,
                               {'ntiid': self.enrollment_ntiid},
                               status=201,
                               extra_environ=environ)

    def _get_course_ext(self, environ):
        if not self.course_ntiid:
            entry = self.testapp.get(self.course_href, extra_environ=environ)
            entry = entry.json_body
            self.course_ntiid = entry.get('CourseNTIID')
        result = self.testapp.get('/dataserver2/Objects/%s' % self.course_ntiid,
                                  extra_environ=environ)
        return result.json_body

    def _test_course_ext(self, environ, is_visible=True):
        if is_visible:
            link_check = self.require_link_href_with_rel
        else:
            link_check = self.forbid_link_with_rel
        course_ext = self._get_course_ext(environ)

        for rel in ('AssignmentSavepoints', 'AssignmentHistory',
                    'AssignmentsByOutlineNode', 'NonAssignmentAssessmentItemsByOutlineNode',
                    'AssignmentMetadata', 'InquiryHistory'):
            link_check(course_ext, rel)

    @WithSharedApplicationMockDS(users=('test_student',), testapp=True)
    @fudge.patch('nti.app.products.courseware.utils.PreviewCourseAccessPredicate._is_preview')
    def test_preview_decorators(self, mock_is_preview):
        mock_is_preview.is_callable().returns(False)
        student_env = self._make_extra_environ('test_student')
        instructor_env = self._make_extra_environ('harp4162')
        self._do_enroll(student_env)

        # Base case
        self._test_course_ext(student_env, is_visible=True)

        # Preview mode
        mock_is_preview.is_callable().returns(True)
        self._test_course_ext(student_env, is_visible=False)

        # Preview mode w/instructor
        self._test_course_ext(instructor_env, is_visible=True)


class TestAssessmentDecorators(ApplicationLayerTest):

    layer = PersistentInstructedCourseApplicationTestLayer

    default_origin = 'http://platform.ou.edu'

    course_href = '/dataserver2/Objects/tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'
    course_ntiid = None

    enrolled_courses_href = '/dataserver2/users/test_student/Courses/EnrolledCourses'
    enrollment_ntiid = u'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2013_CLC3403_LawAndJustice'

    def _do_enroll(self, environ):
        self.testapp.post_json(self.enrolled_courses_href,
                               {'ntiid': self.enrollment_ntiid},
                               status=201,
                               extra_environ=environ)

    def _get_assess_ext(self, environ):
        if not self.course_ntiid:
            entry = self.testapp.get(self.course_href, extra_environ=environ)
            entry = entry.json_body
            self.course_ntiid = entry.get('CourseNTIID')
        result = self.testapp.get('/dataserver2/Objects/%s/AssignmentsByOutlineNode' % self.course_ntiid,
                                  extra_environ=environ)
        return result.json_body.get('Items')

    def _test_course_ext(self, environ, is_editor):
        edit_check = self.require_link_href_with_rel if is_editor else self.forbid_link_with_rel

        assess_items = self._get_assess_ext(environ)

        for item in assess_items:
            for rel in ('date-edit-start', 'date-edit-end', 'audit_log', 'schema'):
                edit_check(item, rel)

    @WithSharedApplicationMockDS(users=('test_student',), testapp=True)
    def test_assess_edit_links(self):
        student_env = self._make_extra_environ('test_student')
        instructor_env = self._make_extra_environ('jmadden')
        editor_env = self._make_extra_environ('harp4162')
        self._do_enroll(student_env)

        self._test_course_ext(student_env, is_editor=False)
        self._test_course_ext(instructor_env, is_editor=False)
        self._test_course_ext(editor_env, is_editor=True)
