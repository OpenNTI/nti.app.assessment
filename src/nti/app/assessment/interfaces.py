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
from zope.interface.common.mapping import IReadMapping
from zope.container.interfaces import IContained
from zope.container.constraints import contains
from zope.container.constraints import containers

from nti.utils import schema

from nti.dataserver.interfaces import ILastModified
from nti.dataserver.interfaces import ICreated

from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment


class IUsersCourseAssignmentHistory(IReadMapping):
	"""
	A :class:`IContainer`-like object that stores the history
	of assignments for a particular user in a course. The keys
	of this object are :class:`IAssignment` IDs (this class may or may
	not enforce that the assignment ID is actually scoped to the course
	it is registered for). The values are instances of :class:`.IUsersCourseAssignmentHistoryItem`.

	Implementations of this object are typically found as a multi-adapter
	between a particular :class:`.ICourseInstance` and an :class:`.IUser`.
	Their ``__parent__`` will be the course instance; therefore, items
	stored in this object will have the course they were assigned by
	in their lineage.

	This object is not an :class:`.IContainer` in the sense that it
	does not emit lifecycle events or otherwise take ownership
	(claim ``__parent__``) of the objects given to it (though it
	will take ownership and emit events for the :class:`.IUsersCourseAssignmentHistoryItem`
	it creates and manages).
	"""

	contains(b'.IUsersCourseAssignmentHistoryItem')

	def recordSubmission( submission, pending_assessment ):
		"""
		When a user submits an assignment, call this method to record
		that fact. If a submission has already been recorded, this will
		raise the standard container error, so use ``in`` first of that's
		a problem.

		:param submission: The original :class:`.IQAssignmentSubmission`
			the user provided.
		:param pending_assessment: The in-progress assessment object
			initially derived from the submission (and that the user
			will store).
		:return: The new :class:`.IUsersCourseAssignmentItem` representing
			the record of this submission.
		"""

class IUsersCourseAssignmentHistoryItem(IContained,
										ILastModified,
										ICreated):
	"""
	A record of something being submitted for an assignment.

	.. note:: This will probably grow much.
	"""
	containers(IUsersCourseAssignmentHistory)

	# Recall that the implementation of AssignmentSubmission is NOT
	# Persistent.
	Submission = schema.Object(IQAssignmentSubmission,
							   required=False)

	# This object is persistent, and should be modified
	# in place if needed.
	pendingAssessment = schema.Object(IQAssignmentSubmissionPendingAssessment,
									  required=False)
