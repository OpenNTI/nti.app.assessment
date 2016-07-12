#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

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
does_not = is_not

from urllib import quote
from itertools import chain

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

class TestAssignmentViews(ApplicationLayerTest):

	layer = InstructedCourseApplicationTestLayer

	default_origin = b'http://janux.ou.edu'

	course_ntiid = 'tag:nextthought.com,2011-10:NTI-CourseInfo-Fall2015_CS_1323'
	course_url = '/dataserver2/%2B%2Betc%2B%2Bhostsites/platform.ou.edu/%2B%2Betc%2B%2Bsite/Courses/Fall2015/CS%201323'
	assignment_id = 'tag:nextthought.com,2011-10:OU-NAQ-CS1323_F_2015_Intro_to_Computer_Programming.naq.asg.assignment:Project_1'

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_content_assignment_date_editing(self):
		editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
		new_start_date = "2014-09-10T05:00:00Z"
		new_end_date = "2015-11-12T04:59:00Z"
		start_field = 'available_for_submission_beginning'
		end_field = 'available_for_submission_ending'
		public_field = 'is_non_public'

		# Base cases
		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
								extra_environ=editor_environ)

		res = res.json_body
		orig_start_date = res.get(start_field)
		orig_end_date = res.get(end_field)
		orig_non_public = res.get(public_field)
		assert_that(orig_non_public, is_(True))
		assert_that(res.get( 'auto_grade' ), none())
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
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ)

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that(res.get(start_field), is_(new_start_date))
		assert_that(res.get(start_field), is_not(orig_start_date))

		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

		data = { end_field: new_end_date }
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ)

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
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
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ)

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
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
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ,
							  status=422)

		# Change to timed assignment
		max_time = 300
		data = { 'maximum_time_allowed': max_time }
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ)

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
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
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ)

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
							   extra_environ=editor_environ)
		res = res.json_body
		assert_that( res.get( 'Class' ), is_( 'TimedAssignment' ) )
		assert_that( res.get( 'MimeType' ), is_( TIMED_ASSIGNMENT_MIME_TYPE ) )
		assert_that( res.get( 'IsTimedAssignment' ), is_( True ) )
		assert_that( res.get( 'MaximumTimeAllowed' ), is_( max_time ) )
		assert_that( res.get( 'NTIID' ), is_( self.assignment_id ) )

		# Change to untimed assignment
		data = { 'maximum_time_allowed': None }
		self.testapp.put_json('/dataserver2/Objects/%s' % self.assignment_id,
							  data, extra_environ=editor_environ)

		res = self.testapp.get('/dataserver2/Objects/' + self.assignment_id,
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

	@WithSharedApplicationMockDS(users=True, testapp=True)
	def test_assignment_editing_invalid(self):
		editor_environ = self._make_extra_environ(username="sjohnson@nextthought.com")
		past_date_str = "2015-09-10T05:00:00Z"
		future_date_str = "2215-09-10T05:00:00Z"
		start_field = 'available_for_submission_beginning'
		end_field = 'available_for_submission_ending'
		assignment_url = '/dataserver2/Objects/%s' % self.assignment_id
		confirm_rel = 'confirm'
		conflict_class = 'DestructiveChallenge'
		conflict_mime = 'application/vnd.nextthought.destructivechallenge'

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

		# Base: 8.25.2015, 9.1.2015
		# Note: we allow state to move from closed in past to
		# closed, but will reopen in the future unchecked (edge case).
		# Move our end date to make us currently open.
		self.testapp.put_json(assignment_url + '?force=True',
							  {end_field: future_date_str},
							  extra_environ=editor_environ)

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

		# 5. Empty start/end dates is unavailable (non-published).
		# This is the new assignment state.
		data = { end_field: None, start_field: None }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res, confirm_code=True)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, none())
		assert_that(new_end_field, none())

		# 5a. No dates set to start date in future works.
		data = { end_field: None, start_field: future_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_( future_date_str ))
		assert_that(new_end_field, none())

		# 5b. Now open with start date in past.
		data = { start_field: past_date_str, end_field: None }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_( past_date_str ))
		assert_that(new_end_field, none())

		# 6. Open to end_date in past.
		data = { end_field: past_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res, confirm_code=True)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_( past_date_str ))
		assert_that(new_end_field, is_(past_date_str))

		# 7. Currently closed to empty end date.
		data = { end_field: None }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res, confirm_code=True)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_( past_date_str ))
		assert_that(new_end_field, none())

		# 7a. Open to no dates.
		data = { start_field: None }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ,
									status=409)
		force_url = _validate_conflict(res, confirm_code=True)
		# Now force it.
		self.testapp.put_json(force_url, data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, none())
		assert_that(new_end_field, none())

		# 8. No dates set (closed) to start_date in future.
		data = { start_field: future_date_str }
		res = self.testapp.put_json(assignment_url,
									data, extra_environ=editor_environ)
		new_start_field, new_end_field = _get_date_fields()
		assert_that(new_start_field, is_(future_date_str))
		assert_that(new_end_field, none())

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

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_no_context(self):
		url = '/dataserver2/Objects/' + self.assignment_id
		data = {'available_for_submission_beginning':'2015-11-25T05:00:00Z',
				'available_for_submission_ending':'2015-11-30T05:00:00Z'}
		self.testapp.put_json(url, data, status=200)
		with mock_dataserver.mock_db_trans(self.ds, 'janux.ou.edu'):
			asg = find_object_with_ntiid(self.assignment_id)
			ending = datetime_from_string('2015-11-30T05:00:00Z')
			beginning = datetime_from_string('2015-11-25T05:00:00Z')

			assert_that(asg, has_property('available_for_submission_ending', is_(ending)))
			assert_that(asg, has_property('available_for_submission_beginning', is_(beginning)))

			history = ITransactionRecordHistory(asg)
			assert_that(history, has_length(1))

			entry = find_object_with_ntiid(self.course_ntiid)
			course = ICourseInstance(entry)
			subs = get_course_subinstances(course)
			for course in chain((course,), subs):
				policies = IQAssessmentPolicies(course)
				data = policies[self.assignment_id]
				assert_that(data, has_entry('locked', is_(True)))

				dates = IQAssessmentDateContext(course)
				data = dates[self.assignment_id]
				assert_that(data, has_entry('available_for_submission_ending', is_(ending)))
				assert_that(data, has_entry('available_for_submission_beginning', is_(beginning)))

	@WithSharedApplicationMockDS(testapp=True, users=True)
	def test_with_context(self):
		url = '/dataserver2/Objects/' + self.assignment_id + "?course=%s" % quote(self.course_ntiid)
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
