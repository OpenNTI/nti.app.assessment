#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import is_not
from hamcrest import not_none
from hamcrest import assert_that
from hamcrest import less_than
does_not = is_not

from zope import interface
from zope import component

from nti.app.assessment.interfaces import IUsersCourseAssignmentMetadata

from nti.assessment.interfaces import IQTimedAssignment

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.app.testing.decorators import WithSharedApplicationMockDS
from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.users import User

from nti.dataserver.tests import mock_dataserver

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

class TestTimedAssignments(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
	assignment_id = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'

	def _do_test_timed(self):
		assignment_url = '/dataserver2/Objects/' + self.assignment_id
		timed_assignment = self.testapp.get( assignment_url )
		timed_assignment = timed_assignment.json_body

		commence_href = self.require_link_href_with_rel(timed_assignment, 'Commence')
		self.require_link_href_with_rel(timed_assignment, 'Metadata')
		self.forbid_link_with_rel(timed_assignment, 'StartTime')
		self.forbid_link_with_rel(timed_assignment, 'TimeRemaining')

		# Start assignment
		res = self.testapp.post( commence_href )
		res = res.json_body

		self.forbid_link_with_rel(res, 'Commence')
		self.require_link_href_with_rel(res, 'Metadata')
		start_href = self.require_link_href_with_rel(res, 'StartTime')
		remaining_href = self.require_link_href_with_rel(res, 'TimeRemaining')

		# Start time
		start_res = self.testapp.get( start_href )
		original_start_time = start_res.json_body.get( 'StartTime' )
		assert_that( original_start_time, not_none())

		# Remaining time
		remaining_res = self.testapp.get( remaining_href )
		original_remaining_time = remaining_res.json_body.get( 'TimeRemaining' )
		assert_that( original_remaining_time, not_none() )

		# Progresses
		remaining_res = self.testapp.get( remaining_href )
		remaining_time = remaining_res.json_body.get( 'TimeRemaining' )
		assert_that( remaining_time, not_none() )
		assert_that( remaining_time, less_than( original_remaining_time ) )

		# Progress by moving our start time back 30s
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			course = find_object_with_ntiid( self.course_ntiid )
			course = ICourseInstance( course )
			user = User.get_user( 'sjohnson@nextthought.com' )
			container = component.getMultiAdapter((course, user),
											  	IUsersCourseAssignmentMetadata)

			metadata = container[self.assignment_id]
			# timestamp
			metadata.StartTime = metadata.StartTime - 30000

		# Start time has changed
		start_res = self.testapp.get( start_href )
		start_time = start_res.json_body.get( 'StartTime' )
		assert_that( start_time, is_not( original_start_time ))

		# Remaining time is now zero
		remaining_res = self.testapp.get( remaining_href )
		remaining_time = remaining_res.json_body.get( 'TimeRemaining' )
		assert_that( remaining_time, is_( 0 ) )

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_timed(self):
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			assignment = find_object_with_ntiid(self.assignment_id)
			interface.alsoProvides( assignment, IQTimedAssignment )
			assignment.maximum_time_allowed = 30 #s

		try:
			self._do_test_timed()
		finally:
			with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
				assignment = find_object_with_ntiid(self.assignment_id)
				interface.noLongerProvides( assignment, IQTimedAssignment )