#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_not
does_not = is_not

from nti.app.assessment.tests import RegisterAssignmentLayer
from nti.app.assessment.tests import RegisterAssignmentLayerMixin

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS


class TestNoteCreation(RegisterAssignmentLayerMixin, ApplicationLayerTest):
    """
    We can not create notes an any component of an assignment
    """
    layer = RegisterAssignmentLayer

    default_origin = 'http://janux.ou.edu'

    def _do_post(self, container):
        data = {'Class': 'Note',
                'ContainerId': container,
                'MimeType': 'application/vnd.nextthought.note',
                'applicableRange': {'Class': 'ContentRangeDescription'},
                'body': ['The body']}

        self.post_user_data(data, status=422)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_cannot_post_to_page(self):
        self._do_post(self.lesson_page_id)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_cannot_post_to_assignment(self):
        self._do_post(self.assignment_id)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_cannot_post_to_question_set(self):
        self._do_post(self.question_set_id)

    @WithSharedApplicationMockDS(users=True, testapp=True)
    def test_cannot_post_to_question(self):
        self._do_post(self.question_id)
