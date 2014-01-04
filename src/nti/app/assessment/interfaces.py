#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Application (integration) level interfaces for assessments.


$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.container.interfaces import IContained
from zope.container.interfaces import IContainer
from zope.container.interfaces import IContainerNamesContainer
from zope.container.constraints import contains
from zope.container.constraints import containers

from nti.utils import schema

from nti.dataserver.interfaces import CompoundModeledContentBody
from nti.dataserver.interfaces import ICreated
from nti.dataserver.interfaces import ILastModified
from nti.dataserver.interfaces import ILastViewed
from nti.dataserver.interfaces import IModeledContent
from nti.dataserver.interfaces import INeverStoredInSharedStream
from nti.dataserver.interfaces import IShouldHaveTraversablePath
from nti.dataserver.interfaces import ITitledContent
from nti.dataserver.interfaces import IUser


from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

class IUsersCourseAssignmentHistories(IContainer,IShouldHaveTraversablePath):
	"""
	A container for all the assignment histories in a course, keyed
	by username.
	"""
	contains(str('.IUsersCourseAssignmentHistory'))

class IUsersCourseAssignmentHistory(IContainer,
									ILastViewed,
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
	owner = schema.Object(IUser,
						  required=False,
						  title="The user this history is for.")
	owner.setTaggedValue('_ext_excluded_out', True)

	Items = schema.Dict(title='For externalization only, a copy of the items',
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
														 IShouldHaveTraversablePath):
	"""
	A container for feedback items.
	"""
	contains(str('.IUsersCourseAssignmentHistoryItemFeedback'))
	__setitem__.__doc__ = None
	Items = schema.List(title="The contained feedback items",
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
	Submission = schema.Object(IQAssignmentSubmission,
							   required=False)

	# This object is persistent, and should be modified
	# in place if needed.
	pendingAssessment = schema.Object(IQAssignmentSubmissionPendingAssessment,
									  required=False)

	Feedback = schema.Object(IUsersCourseAssignmentHistoryItemFeedbackContainer,
							 required=False)

class IUsersCourseAssignmentHistoryItemFeedback(IContained,
												IModeledContent,
												ITitledContent,
												INeverStoredInSharedStream,
												IShouldHaveTraversablePath):
	"""
	A feedback item on a history item.
	"""

	containers(IUsersCourseAssignmentHistoryItemFeedbackContainer) # Adds __parent__ as required
	__parent__.required = False

	body = CompoundModeledContentBody()

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
