#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Application (integration) level interfaces for assessments.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

from zope import interface
from zope import component

from zope.container.constraints import contains
from zope.container.interfaces import IContained
from zope.container.interfaces import IContainer
from zope.container.constraints import containers
from zope.container.interfaces import IContainerNamesContainer

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQSurveySubmission

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ICreated
from nti.dataserver.interfaces import ILastViewed
from nti.dataserver.interfaces import ILastModified
from nti.dataserver.interfaces import ITitledContent
from nti.dataserver.interfaces import IModeledContent
from nti.dataserver.interfaces import CompoundModeledContentBody
from nti.dataserver.interfaces import INeverStoredInSharedStream
from nti.dataserver.interfaces import IShouldHaveTraversablePath

from nti.schema.field import Int
from nti.schema.field import Dict
from nti.schema.field import List
from nti.schema.field import Float
from nti.schema.field import Number
from nti.schema.field import Object

from zope.security.permission import Permission

ACT_VIEW_SOLUTIONS = Permission('nti.actions.assessment.view_solutions')
ACT_DOWNLOAD_GRADES = Permission('nti.actions.assessment.download_grades')

class IUsersCourseAssignmentSavepoints(IContainer,
									   IContained,
									   IShouldHaveTraversablePath):
	"""
	A container for all the assignment save points in a course, keyed by username.
	"""
	contains(str('.IUsersCourseAssignmentSavepoint'))

class IUsersCourseAssignmentSavepoint(IContainer,
									  IContained,
									  IShouldHaveTraversablePath):
	"""
	A :class:`IContainer`-like object that stores the save point of
	assignments for a particular user in a course. The keys of this
	object are :class:`IAssignment` IDs (this class may or may not
	enforce that the assignment ID is actually scoped to the course it
	is registered for). The values are instances of :class:`.IQAssignmentSubmission`.
	"""

	contains(str('.IUsersCourseAssignmentSavepointItem'))
	containers(IUsersCourseAssignmentSavepoints)
	__setitem__.__doc__ = None

	owner = Object(IUser, required=False, title="The user this save point is for.")
	owner.setTaggedValue('_ext_excluded_out', True)

	Items = Dict(title='For externalization only, a copy of the items', readonly=True)

	def recordSubmission(submission,  event=False):
		"""
		When a user submits an assignment for save point call this method to record
		that fact. If a submission has already been recorded, this will
		replace the previous one

		:param submission: The original :class:`.IQAssignmentSubmission`
			the user provided. We will become part of the lineage
			of this object and all its children objects (they will
			be set to the correct __parent__ relationship within the part/question
			structure).
			
		:param event: Flag to avoid sending an add/modified event
		
		:return: The new :class:`.IUsersCourseAssignmentSavepointItem` representing
				 the record of this submission.
		"""
		
	def removeSubmission(submission, event=False):
		"""
		remove a submission
		
		:param submission: The :class:`.IQAssignmentSubmission` to remove
		:param event: Flag to avoid sending a removal/modified event
		"""

class IUsersCourseAssignmentSavepointItem(IContained, 
										  ILastModified,
										  ICreated,
										  IShouldHaveTraversablePath):

	containers(IUsersCourseAssignmentSavepoint)
	__parent__.required = False

	Submission = Object(IQAssignmentSubmission, required=False)

class IUsersCourseAssignmentHistories(IContainer,
									  IContained,
									  IShouldHaveTraversablePath):
	"""
	A container for all the assignment histories in a course, keyed
	by username.
	"""
	contains(str('.IUsersCourseAssignmentHistory'))

class IUsersCourseAssignmentHistory(IContainer,
									ILastViewed,
									IContained,
									IShouldHaveTraversablePath):
	"""
	A :class:`IContainer`-like object that stores the history of
	assignments for a particular user in a course. The keys of this
	object are :class:`IAssignment` IDs (this class may or may not
	enforce that the assignment ID is actually scoped to the course it
	is registered for). The values are instances of
	:class:`.IUsersCourseAssignmentHistoryItem`.

	Implementations of this object are typically found as a
	multi-adapter between a particular :class:`.ICourseInstance` and
	an :class:`.IUser`. Their ``__parent__`` will be the course
	instance; therefore, items stored in this object will have the
	course they were assigned by in their lineage.

	This object claims storage and ownership of the objects given to it through
	:meth:`recordSubmission`. Lifecycle events will be emitted for
	the creation of the :class:`IUsersCourseAssignmentHistoryItem`,
	the addition of that item, and finally the addition of the pending assessment
	(at that point, the submission's and pending assessment's ``__parent__``
	will be the history item which in turn will be parented by this object.)
	"""

	contains(str('.IUsersCourseAssignmentHistoryItem'))
	containers(IUsersCourseAssignmentHistories)
	__setitem__.__doc__ = None

	owner = Object(IUser, required=False, title="The user this history is for.")
	owner.setTaggedValue('_ext_excluded_out', True)

	Items = Dict(title='For externalization only, a copy of the items',
			 	 readonly=True)

	def recordSubmission( submission, pending_assessment ):
		"""
		When a user submits an assignment, call this method to record
		that fact. If a submission has already been recorded, this will
		raise the standard container error, so use ``in`` first of that's
		a problem.

		:param submission: The original :class:`.IQAssignmentSubmission`
			the user provided. We will become part of the lineage
			of this object and all its children objects (they will
			be set to the correct __parent__ relationship within the part/question
			structure).
		:param pending_assessment: The in-progress assessment object
			initially derived from the submission (and that the user
			will store). We will become part of the lineage of this object.
		:return: The new :class:`.IUsersCourseAssignmentItem` representing
			the record of this submission.
		"""

class IUsersCourseAssignmentHistoryItemFeedbackContainer(IContainerNamesContainer,
														 ICreated,
														 ILastModified,
														 IShouldHaveTraversablePath):
	"""
	A container for feedback items.
	"""
	contains(str('.IUsersCourseAssignmentHistoryItemFeedback'))
	__setitem__.__doc__ = None

	Items = List(title="The contained feedback items",
			 	 description="Unlike forums, we expect very few of these, so we "
				 			 "inline them for externalization.",
				 readonly=True)

class IUsersCourseAssignmentHistoryItem(IContained,
										ILastModified,
										ICreated,
										IShouldHaveTraversablePath):
	"""
	A record of something being submitted for an assignment.

	.. note:: This will probably grow much.
	"""
	containers(IUsersCourseAssignmentHistory)
	__parent__.required = False

	# Recall that the implementation of AssignmentSubmission is NOT
	# Persistent.
	Submission = Object(IQAssignmentSubmission, required=False)

	# This object is persistent, and should be modified
	# in place if needed.
	pendingAssessment = Object(IQAssignmentSubmissionPendingAssessment,
							   required=False)

	Feedback = Object(IUsersCourseAssignmentHistoryItemFeedbackContainer,
					  required=False)

	FeedbackCount = Int(title="How many feedback items", default=0)
	
	Assignment = Object(IQAssignment, title="The assigment that generated this item",
						required=False)
	Assignment.setTaggedValue('_ext_excluded_out', True)

class IUsersCourseAssignmentHistoryItemSummary(IContained,
											   ILastModified,
											   ICreated,
											   IShouldHaveTraversablePath):
	"""
	A quick summary of a complete history item, typically for
	fast externalization purposes.
	"""

	FeedbackCount = Int(title="How many feedback items", default=0)

	SubmissionCreatedTime = Number(title=u"The timestamp at which the submission object was created.",
								   description="Typically set automatically by the object.",
								   default=0.0)


class IUsersCourseAssignmentHistoryItemFeedback(IContained,
												IModeledContent,
												ITitledContent,
												INeverStoredInSharedStream,
												IShouldHaveTraversablePath):
	"""
	A feedback item on a history item.

	Notice that these are not :class:`.IThreadable`; all feedback
	is considered to be top-level.
	"""

	containers(IUsersCourseAssignmentHistoryItemFeedbackContainer) # Adds __parent__ as required
	__parent__.required = False

	body = CompoundModeledContentBody()


class ICourseAssessmentItemCatalog(interface.Interface):
	"""
	Provides access to the assessment items (questions, question sets,
	assignments) related to a course.

	Typically this will be registered as an adapter
	from the :class:`.ICourseInstance`.
	"""

	def iter_assessment_items():
		"""
		Return the items.

		Recall that items typically will have their 'home'
		content unit in their lineage.
		"""

class ICourseAssignmentCatalog(interface.Interface):
	"""
	Provides access to the assignments related to a course.

	Typically this will be registered as an adapter
	from the :class:`.ICourseInstance`.
	"""

	def iter_assignments():
		"""
		Return the assignments.

		Recall that assignments typically will have their 'home'
		content unit in their lineage.
		"""

class ICourseAssignmentUserFilter(interface.Interface):
	"""
	A filter to determine if a user should be able to see
	an assignment.

	These will typically be registered as subscription adapters
	from the user and the course.
	"""

	def allow_assignment_for_user_in_course(assignment, user, course):
		"""
		Given a user and an :class:`.ICourseInstance` the user is enrolled in, return a
		callable that takes an assignment and returns True if the
		assignment should be visible to the user and False otherwise.
		"""

def get_course_assignment_predicate_for_user(user, course):
	"""
	Given a user and an :class:`.ICourseInstance` the user is enrolled in, return a
	callable that takes an assignment and returns True if the
	assignment should be visible to the user and False otherwise.

	Delegates to :class:`.ICourseAssignmentUserFilter` subscribers.

	.. note:: Those subscribers probably implicitly assume that
		the assignment passed to them is actually hosted within the
		course.
	"""
	filters = component.subscribers((user, course), ICourseAssignmentUserFilter)
	filters = list(filters) # Does that return a generator? We need to use it many times
	def uber_filter(asg):
		return all((f.allow_assignment_for_user_in_course(asg, user, course) for f in filters))

	return uber_filter

class IUsersCourseAssignmentMetadataContainer(IContainer,
										  	  IContained,
										  	  IShouldHaveTraversablePath):
	"""
	A container for all the assignment meta data in a course, keyed by username.
	"""
	contains(str('.IUsersCourseAssignmentMetadata'))
	
class IUsersCourseAssignmentMetadata(IContainer,
									 IContained,
									 IShouldHaveTraversablePath):
	"""
	A :class:`IContainer`-like object that stores metadata of 
	assignments for a particular user in a course. The keys of this
	object are :class:`IAssignment` IDs (this class may or may not
	enforce that the assignment ID is actually scoped to the course it
	is registered for). The values are instances of :class:`.IUsersCourseAssignmentMetadataItem`.
	"""

	contains(str('.IUsersCourseAssignmentMetadataItem'))
	containers(IUsersCourseAssignmentMetadataContainer)
	__setitem__.__doc__ = None

	owner = Object(IUser, required=False, title="The user this metadata is for.")
	owner.setTaggedValue('_ext_excluded_out', True)

	Items = Dict(title='For externalization only, a copy of the items', readonly=True)

class IUsersCourseAssignmentMetadataItem(interface.Interface):
	containers(IUsersCourseAssignmentMetadata)
	__parent__.required = False

	StartTime = Float(title="Assignment Start time", required=False)
	Duration = Float(title="Assignment Duration", required=False)

class IUsersCourseSurveys(IContainer,
						  IContained,
						  IShouldHaveTraversablePath):
	"""
	A container for all the survey in a course, keyed by username.
	"""
	contains(str('.IUsersCourseSurvey'))

class IUsersCourseSurvey(IContainer,
						 ILastViewed,
						 IContained,
						 IShouldHaveTraversablePath):
	"""
	A :class:`IContainer`-like object that stores the history of
	survey for a particular user in a course. The keys of this
	object are :class:`IQSurvey` IDs (this class may or may not
	enforce that the survey ID is actually scoped to the course it
	is registered for). The values are instances of
	:class:`.IUsersCourseSurveyItem`.

	Implementations of this object are typically found as a
	multi-adapter between a particular :class:`.ICourseInstance` and
	an :class:`.IUser`. Their ``__parent__`` will be the course
	instance; therefore, items stored in this object will have the
	course they were assigned by in their lineage.

	This object claims storage and ownership of the objects given to it through
	:meth:`recordSubmission`. Lifecycle events will be emitted for
	the creation of the :class:`IUsersCourseSurveyItem`
	"""

	contains(str('.IUsersCourseSurveyItem'))
	containers(IUsersCourseSurveys)
	__setitem__.__doc__ = None

	owner = Object(IUser, required=False, title="The user this survey is for.")
	owner.setTaggedValue('_ext_excluded_out', True)

	Items = Dict(title='For externalization only, a copy of the items',
			 	 readonly=True)

	def recordSubmission( submission ):
		"""
		When a user submits a survey, call this method to record
		that fact. If a submission has already been recorded, this will
		raise the standard container error, so use ``in`` first of that's
		a problem.

		:param submission: The original :class:`.IQSurveySubmission`
			the user provided. We will become part of the lineage
			of this object and all its children objects (they will
			be set to the correct __parent__ relationship within the part/question
			structure).
		:return: The new :class:`.IUsersCourseSurveyItem` representing
			the record of this submission.
		"""

class IUsersCourseSurveyItem(IContained,
						  	 ILastModified,
							 ICreated,
							 IShouldHaveTraversablePath):
	"""
	A record of something being submitted for an survey.
	"""
	containers(IUsersCourseSurvey)
	__parent__.required = False

	# Recall that the implementation of SurveySubmission is NOT Persistent.
	Submission = Object(IQSurveySubmission, required=False)

	Survey = Object(IQSurvey, title="The survey that generated this item",
					required=False)
	Survey.setTaggedValue('_ext_excluded_out', True)
