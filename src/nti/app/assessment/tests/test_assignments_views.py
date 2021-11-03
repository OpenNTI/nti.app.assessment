#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import is_
from hamcrest import none
from hamcrest import is_not
from hamcrest import has_item
from hamcrest import not_none
from hamcrest import has_entry
from hamcrest import has_length
from hamcrest import has_property
from hamcrest import assert_that
from hamcrest import greater_than
does_not = is_not

from zope import component
from zope import interface

from zope.intid.interfaces import IIntIds

from nti.app.assessment import get_evaluation_catalog

from nti.app.assessment.index import IX_MIMETYPE

from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.assessment.interfaces import ASSIGNMENT_MIME_TYPE
from nti.assessment.interfaces import TIMED_ASSIGNMENT_MIME_TYPE

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQTimedAssignment
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssessmentPolicies
from nti.assessment.interfaces import IQAssessmentDateContext

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.externalization.datetime import datetime_from_string

from nti.ntiids.ntiids import find_object_with_ntiid

from nti.recorder.interfaces import ITransactionRecordHistory

from nti.app.products.courseware.tests import InstructedCourseApplicationTestLayer

from nti.app.testing.application_webtest import ApplicationLayerTest

from nti.app.testing.decorators import WithSharedApplicationMockDS

from nti.dataserver.tests import mock_dataserver

from nti.testing.time import time_monotonically_increases

class TestAssignmentViews(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
	course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'
	assignment_id = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'
	assignment_url = '/dataserver2/Objects/%s?course=%s' % (assignment_id, course_ntiid)

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_assignment_editing(self):
		editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
		new_start_date = "2014-09-10T05:00:00Z"
		new_end_date = "2015-11-12T04:59:00Z"
		start_field = 'available_for_submission_beginning'
		end_field = 'available_for_submission_ending'
		public_field = 'is_non_public'
		assignment_url = self.assignment_url

		# Base cases
		res = self.testapp.get(assignment_url,
								extra_environ=editor_environ)

		res = res.json_body
		orig_start_date = res.get(start_field)
		orig_end_date = res.get(end_field)
		orig_non_public = res.get(public_field)
		assert_that(orig_non_public, is_(True))
		assert_that(res.get( 'auto_grade' ), is_( False ))
		assert_that(res.get( 'total_points' ), none())

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			# Mark assignment/question_set editable for testing purposes.
			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)
			asg = find_object_with_ntiid(self.assignment_id)
			asg.__parent__ = course
			interface.alsoProvides(asg, IQEditableEvaluation)
			qset = asg.parts[0].question_set
			qset.__parent__ = course
			interface.alsoProvides(qset, IQEditableEvaluation)
			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(0))

		# Test editing dates
		data = { start_field: new_start_date }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ)

		res = self.testapp.get(assignment_url,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get(start_field), is_(new_start_date))
		assert_that(res.get(start_field), is_not(orig_start_date))

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

		data = { end_field: new_end_date }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ)

		res = self.testapp.get(assignment_url,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get(end_field), is_(new_end_date))
		assert_that(res.get(end_field), is_not(orig_end_date))

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(2))

		# Edit is_non_public
		data = { public_field: 'False' }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ)

		res = self.testapp.get(assignment_url,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get(public_field), is_(False))
		assert_that(res.get(public_field), is_not(True))

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(3))

		# Invalid timed assignment
		data = { 'maximum_time_allowed': -1 }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ,
							  status=422)

		# Change to timed assignment
		max_time = 300
		data = { 'maximum_time_allowed': max_time }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ)

		res = self.testapp.get(assignment_url,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that( res.get( 'Class' ), is_( 'TimedAssignment' ) )
		assert_that( res.get( 'MimeType' ), is_( TIMED_ASSIGNMENT_MIME_TYPE ) )
		assert_that( res.get( 'IsTimedAssignment' ), is_( True ) )
		assert_that( res.get( 'MaximumTimeAllowed' ), is_( max_time ) )
		assert_that( res.get( 'NTIID' ), is_( self.assignment_id ) )
		assert_that( res.get( 'parts' ), has_length( 1 ))

		def _get_timed():
			cat = get_evaluation_catalog()
			timed_objs = tuple( cat.apply(
									{IX_MIMETYPE:
										{'any_of': (TIMED_ASSIGNMENT_MIME_TYPE,)}}))
			return timed_objs

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			obj = component.queryUtility( IQTimedAssignment, name=self.assignment_id )
			assert_that( obj, not_none() )
			assert_that( obj.ntiid, is_( self.assignment_id ))
			assert_that( obj, is_( asg ))
			intids = component.getUtility(IIntIds)
			obj_id = intids.getId( obj )
			timed_objs = _get_timed()
			assert_that( timed_objs, has_item( obj_id ))

		# Change fields but retain timed status
		data =  {'available_for_submission_beginning': 1471010400,
				 'available_for_submission_ending': 1471017600}
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ)

		res = self.testapp.get(assignment_url,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that( res.get( 'Class' ), is_( 'TimedAssignment' ) )
		assert_that( res.get( 'MimeType' ), is_( TIMED_ASSIGNMENT_MIME_TYPE ) )
		assert_that( res.get( 'IsTimedAssignment' ), is_( True ) )
		assert_that( res.get( 'MaximumTimeAllowed' ), is_( max_time ) )
		assert_that( res.get( 'NTIID' ), is_( self.assignment_id ) )

		# Change to untimed assignment
		data = { 'maximum_time_allowed': None }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ)

		res = self.testapp.get(assignment_url,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that( res.get( 'Class' ), is_( 'Assignment' ) )
		assert_that( res.get( 'MimeType' ), is_( ASSIGNMENT_MIME_TYPE ) )
		assert_that( res.get( 'IsTimedAssignment' ), is_( False ) )
		assert_that( res.get( 'MaximumTimeAllowed' ), is_( None ) )
		assert_that( res.get( 'NTIID' ), is_( self.assignment_id ) )

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			obj = component.queryUtility( IQTimedAssignment, name=self.assignment_id )
			assert_that( obj, none() )
			obj = component.queryUtility( IQAssignment, name=self.assignment_id )
			assert_that( obj.ntiid, is_( self.assignment_id ))
			assert_that( obj, is_( asg ))
			intids = component.getUtility(IIntIds)
			obj_id = intids.getId( obj )
			timed_objs = _get_timed()
			assert_that( timed_objs, does_not( has_item( obj_id )))

	@time_monotonically_increases
	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_assignment_policy_editing(self):
		"""
		Test assignment policy editing for a content backed assignment. The client
		generally publishes the object before scheduling any dates (the assignment
		in the test is below). Changing dates in draft mode (unpublished) is untested,
		but should not 409.
		"""
		editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
		past_date_str = "2015-09-10T05:00:00Z"
		future_date_str = "2215-09-10T05:00:00Z"
		start_field = 'available_for_submission_beginning'
		end_field = 'available_for_submission_ending'
		assignment_url = self.assignment_url
		confirm_rel = 'confirm'
		conflict_class = 'DestructiveChallenge'
		conflict_mime = 'application/vnd.nextthought.destructivechallenge'

		# Force the parts to be auto_grade (assessable).
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			for parts in asg.parts or ():
				parts.auto_grade = True

		assignment = self.testapp.get(assignment_url, extra_environ=editor_environ)
		assignment = assignment.json_body
		assert_that( assignment.get( 'policy_locked'), is_( False ))
		assert_that( assignment.get( 'auto_grade'), is_( False ))
		assert_that( assignment.get( 'total_points'), none())
		assert_that( assignment.get( 'submission_buffer'), is_(False))
		assert_that( assignment.get( 'completion_passing_percent'), none())
		for rel in ('date-edit', 'auto-grade', 'total-points',
					'submission-buffer', 'completion-passing-percent'):
			self.require_link_href_with_rel(assignment, rel)
		# Can only toggle API created assignments to timed.
		self.forbid_link_with_rel(assignment, 'maximum-time-allowed')

		def _validate_conflict(conflict_res, confirm_code=False):
			conflict_res = conflict_res.json_body
			confirm_checker = is_ if confirm_code else is_not
			assert_that(conflict_res, has_entry('Class', conflict_class))
			assert_that(conflict_res, has_entry('MimeType', conflict_mime))
			assert_that(conflict_res, has_entry('code',
												confirm_checker(AssessmentPutView.CONFIRM_CODE)))
			return self.require_link_href_with_rel(conflict_res, confirm_rel)

		def _get_date_fields():
			res = self.testapp.get(assignment_url, extra_environ=editor_environ)
			res = res.json_body
			return res.get(start_field), res.get(end_field)

		def _check_publish_last_mod( old_last_mod ):
			res = self.testapp.get(assignment_url, extra_environ=editor_environ)
			res = res.json_body
			last_mod = res.get( 'publishLastModified' )
			assert_that( last_mod, greater_than( old_last_mod ))
			return last_mod

		# Base: 8.25.2015, 9.1.2015
		# Note: we allow state to move from closed in past to
		# closed, but will reopen in the future unchecked (edge case).
		# Move our end date to make us currently open.
		self.testapp.put_json(assignment_url + '&force=True',
							  {end_field: future_date_str},
							  extra_environ=editor_environ)
		last_mod = _check_publish_last_mod( -1 )

		# Test toggling assessment availability
		# 1. Currently open to start date in future
		data = { start_field: future_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_(future_date_str))
		assert_that(new_end_field, is_(future_date_str))
		last_mod = _check_publish_last_mod( last_mod )

		# 2. Currently closed to start date in past
		data = { start_field: past_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_(past_date_str))
		assert_that(new_end_field, is_(future_date_str))
		last_mod = _check_publish_last_mod( last_mod )

		# 3. Currently open to end date in past
		data = { end_field: past_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res, confirm_code=True)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_(past_date_str))
		assert_that(new_end_field, is_(past_date_str))
		last_mod = _check_publish_last_mod( last_mod )

		# 4. Currently closed to end date in future
		data = { end_field: future_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res, confirm_code=True)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_(past_date_str))
		assert_that(new_end_field, is_(future_date_str))
		last_mod = _check_publish_last_mod( last_mod )

		# 5. Currently open to empty start/end dates just works.
		data = { end_field: None, start_field: None }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, none())
		assert_that(new_end_field, none())
		last_mod = _check_publish_last_mod( last_mod )

		# 6. No dates set to end_date in past.
		data = { end_field: past_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, none())
		assert_that(new_end_field, is_(past_date_str))
		last_mod = _check_publish_last_mod( last_mod )

		# 7. Now empty dates.
		data = { end_field: None }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, none())
		assert_that(new_end_field, none())
		last_mod = _check_publish_last_mod( last_mod )

		# 8. No dates set to start_date in future.
		data = { start_field: future_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_(future_date_str))
		assert_that(new_end_field, none())
		last_mod = _check_publish_last_mod( last_mod )

		# 9. Start date after end date
		data = { start_field: future_date_str, end_field : past_date_str }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ,
							  status=422)

		# 10. Derp
		data = { start_field: 'derp' }
		self.testapp.put_json(assignment_url,
							  data, extra_environ=editor_environ,
							  status=422)

		# Other policy edits
		assignment = self.testapp.get(assignment_url, extra_environ=editor_environ)
		assignment = assignment.json_body
		assert_that( assignment.get( 'policy_locked'), is_( True ))
		assert_that( assignment.get( 'auto_grade'), is_( False ))
		assert_that( assignment.get( 'total_points'), none())
		assert_that( assignment.get( 'submission_buffer'), is_(False))

		data = { 'total_points': 100,
				 'submission_buffer': 300 }
		assignment = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		assignment = assignment.json_body
		assert_that( assignment.get( 'policy_locked'), is_( True ))
		assert_that( assignment.get( 'auto_grade'), is_( False ))
		assert_that( assignment.get( 'total_points'), is_( 100 ))
		assert_that( assignment.get( 'submission_buffer'), is_(300))

		# Passing perc
		for bad_passing_perc in (-1, 'a', 0, '2.0', '1.0001'):
			data = { 'completion_passing_percent': bad_passing_perc }
			self.testapp.put_json(assignment_url,
								  data, extra_environ=editor_environ,
								  status=422)
		for valid_passing_perc in (0.1, '.5', 1, None):
			data = { 'completion_passing_percent': valid_passing_perc }
			assignment = self.testapp.put_json(assignment_url,
											   data, extra_environ=editor_environ)
			assignment = assignment.json_body
			try:
				valid_passing_perc = float(valid_passing_perc)
			except TypeError:
				valid_passing_perc = None
			assert_that(assignment.get('completion_passing_percent'),
						is_(valid_passing_perc))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_no_context(self):
		url = self.assignment_url
		data = {'available_for_submission_beginning':'2015-11-25T05:00:00Z',
				'available_for_submission_ending':'2015-11-30T05:00:00Z'}
		self.testapp.put_json(url, data, status=200)
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			ending = datetime_from_string('2015-11-30T05:00:00Z')
			beginning = datetime_from_string('2015-11-25T05:00:00Z')

			# Our assignment dates will not/cannot change.
			assert_that(asg, has_property('available_for_submission_ending', is_not(ending)))
			assert_that(asg, has_property('available_for_submission_beginning', is_not(beginning)))

			# Out assignment is not locked
			assert_that(asg.isLocked(), is_(False))

			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)
			subs = get_course_subinstances(course)
			# But the dates in the course policy do change.
			policies = IQAssessmentPolicies(course)
			data = policies[self.assignment_id]
			assert_that(data, has_entry('locked', is_(True)))

			dates = IQAssessmentDateContext(course)
			data = dates[self.assignment_id]
			assert_that(data, has_entry('available_for_submission_ending', is_(ending)))
			assert_that(data, has_entry('available_for_submission_beginning', is_(beginning)))

			# ...and the subinstances do not.
			for subinstance in subs:
				policies = IQAssessmentPolicies(subinstance)
				data = policies[self.assignment_id]
				assert_that(data, does_not( has_item( 'locked' )))

				dates = IQAssessmentDateContext(subinstance)
				data = dates[self.assignment_id]
				assert_that(data, has_entry('available_for_submission_ending', is_not(ending)))
				assert_that(data, has_entry('available_for_submission_beginning', is_not(beginning)))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_with_context(self):
		url = self.assignment_url
		data = {'available_for_submission_beginning':'2015-11-25T05:00:00Z',
				'available_for_submission_ending':'2015-11-30T05:00:00Z',
				'title':'ProjectOne'}
		# Cannot edit content assignments.
		self.testapp.put_json(url, data, status=422)

		# Mark as editable for testing purposes.
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)
			asg = find_object_with_ntiid(self.assignment_id)
			asg.__parent__ = course
			interface.alsoProvides(asg, IQEditableEvaluation)
		self.testapp.put_json(url, data)

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			ending = datetime_from_string('2015-11-30T05:00:00Z')
			beginning = datetime_from_string('2015-11-25T05:00:00Z')

			assert_that(asg, has_property('title', is_('ProjectOne')))
			assert_that(asg, has_property('available_for_submission_ending', is_not(ending)))
			assert_that(asg, has_property('available_for_submission_beginning', is_not(beginning)))

			# Out assignment is locked since we edited title.
			assert_that(asg.isLocked(), is_(True))

			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)

			policies = IQAssessmentPolicies(course)
			data = policies[self.assignment_id]
			assert_that(data, has_entry('locked', is_(True)))

			dates = IQAssessmentDateContext(course)
			data = dates[self.assignment_id]
			assert_that(data, has_entry('available_for_submission_ending', is_(ending)))
			assert_that(data, has_entry('available_for_submission_beginning', is_(beginning)))
