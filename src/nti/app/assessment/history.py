#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Storage for assignment histories.

.. note:: Even though these are adapters and so might have gone in the
  :mod:`adapters` module, they are also persistent, and as such deserve their
  own module.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from datetime import datetime

from zope import component
from zope import interface
from zope import lifecycleevent
from zope.container.contained import Contained
from zope.cachedescriptors.property import Lazy

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssignmentDateContext

from nti.common.property import alias
from nti.common.property import CachedProperty

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser
from nti.dataserver.authorization import ACT_READ
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.authorization import ACT_DELETE
from nti.dataserver.interfaces import ALL_PERMISSIONS
from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.wref.interfaces import IWeakRef

from nti.zodb.minmax import NumericMaximum
from nti.zodb.minmax import NumericPropertyDefaultingToZero

from ._submission import set_submission_lineage

from .feedback import UsersCourseAssignmentHistoryItemFeedbackContainer

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistories
from .interfaces import IUsersCourseAssignmentHistoryItem
from .interfaces import IUsersCourseAssignmentHistoryItemSummary

@interface.implementer(IUsersCourseAssignmentHistories)
class UsersCourseAssignmentHistories(CaseInsensitiveCheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course assignment histories for all users in a course.
	"""

@interface.implementer(IUsersCourseAssignmentHistory)
class UsersCourseAssignmentHistory(CheckingLastModifiedBTreeContainer):
	"""
	Implementation of the course assignment history for a user (within a course
	although theoretically, because assignment IDs are globally unique,
	we could use a single history).

	Although the primary interface this class implements does not specify the full
	container interface, we do provide it as a side effect.
	"""

	__external_can_create__ = False

	lastViewed = NumericPropertyDefaultingToZero(str('lastViewed'), NumericMaximum, as_number=True)

	#: An :class:`.IWeakRef` to the owning user, who is probably
	#: not in our lineage.
	_owner_ref = None

	def _get_owner(self):
		return self._owner_ref() if self._owner_ref else None
	def _set_owner(self,owner):
		self._owner_ref = IWeakRef(owner)
	owner = property(_get_owner,_set_owner)

	#: A non-interface attribute for convenience (especially with early
	#: acls, since we are ICreated we get that by default)
	creator = alias('owner')

	@property
	def Items(self):
		return dict(self)

	def recordSubmission( self, submission, pending ):
		if submission.__parent__ is not None or pending.__parent__ is not None:
			raise ValueError("Objects already parented")

		item = UsersCourseAssignmentHistoryItem(Submission=submission,
												pendingAssessment=pending )
		pending.__parent__ = item
		submission.__parent__ = item
		set_submission_lineage(submission)

		lifecycleevent.created(item)
		self[submission.assignmentId] = item # fire object added, which is dispatched to sublocations
		return item

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			return self.owner
		if ICourseInstance.isOrExtends(iface):
			return self.__parent__

	@property
	def __acl__(self):
		"""
		Our ACL allows read access for the creator and read/write access
		for the instructors of the course
		"""
		# This is a near-duplicate of the ACL applied to the child items;
		# we could probably remove the child item ACLs if we're assured of good
		# testing? Although we might have to grant CREATE access to the child?
		# (in fact we do)
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing( self.owner, ACT_READ, UsersCourseAssignmentHistory )]
		for instructor in instructors:
			aces.append( ace_allowing(instructor, ALL_PERMISSIONS, UsersCourseAssignmentHistory) )
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

from zope.location.interfaces import ISublocations

def _get_policy_for_assignment(course, asg_id):
	policies = IQAssignmentPolicies(course)
	policy = policies.getPolicyForAssignment(asg_id)
	return policy

def _get_available_for_submission_ending(course, assignment):
	dates = IQAssignmentDateContext(course)
	due_date = dates.of(assignment).available_for_submission_ending
	return due_date

@interface.implementer(IUsersCourseAssignmentHistoryItem,
					   IACLProvider,
					   ISublocations)
class UsersCourseAssignmentHistoryItem(PersistentCreatedModDateTrackingObject,
									   Contained,
									   SchemaConfigured):
	createDirectFieldProperties(IUsersCourseAssignmentHistoryItem)

	__external_can_create__ = False

	@Lazy
	def Feedback(self):
		container = UsersCourseAssignmentHistoryItemFeedbackContainer()
		container.__parent__ = self
		container.__name__ = 'Feedback'
		self._p_changed = True
		return container

	def has_feedback(self):
		self._p_activate()
		return 'Feedback' in self.__dict__ and len(self.Feedback)

	@property
	def FeedbackCount(self):
		if self.has_feedback():
			return len(self.Feedback)
		return 0

	def __conform__(self, iface):
		if IUser.isOrExtends(iface):
			# If the user is deleted, we will not be able to do this
			try:
				return iface(self.__parent__)
			except (AttributeError,TypeError):
				return None

	@property
	def creator(self):
		# For ACL purposes, not part of the interface
		return IUser(self, None)

	@creator.setter
	def creator(self, nv):
		# Ignored
		pass

	@property
	def assignmentId(self):
		return self.__name__

	@property
	def _has_grade(self):
		# sadly can't cache this directly
		from nti.app.products.gradebook.interfaces import IGrade
		try:
			grade = IGrade(self, None)
			# Right now we're taking either a grade or an autograde
			# as disallowing this. the current use case (file submissions)
			# has autograding disabled, but in the future we'd need to be
			# sure to reliably distinguish them if we only want to take into
			# account instructor grades (which I think just means lastModified > createdTime)
			return grade is not None and (grade.value is not None
										  or grade.AutoGrade is not None)
		except (LookupError, TypeError):
			return False

	@CachedProperty('_has_grade')
	def _student_nuclear_reset_capable(self):
		"""
		Nuclear reset capability is defined by:

		#. The ``student_nuclear_reset_capable`` policy flag being true;
		#. The current date being *before* the due date;
		#. The absence of feedback;
		#. The absence of a grade;
		"""
		# Try to arrange the checks in the cheapest possible order
		if self.FeedbackCount:
			return False

		course = ICourseInstance(self, None)
		# our name is the assignment id
		asg_id = self.__name__
		assignment = component.queryUtility(IQAssignment, name=asg_id)
		if course is None or assignment is None:
			# Not enough information, bail
			return False

		policy = _get_policy_for_assignment(course, asg_id)
		if not policy.get('student_nuclear_reset_capable', False):
			# Not allowed!
			# TODO: could probably push this off to syncronization
			# time...have that process apply marker interfaces
			return False

		due_date = _get_available_for_submission_ending(course, assignment)
		if due_date and datetime.utcnow() >= due_date:
			# past due
			return False

		# Now check for a grade. Ideally, this doesn't belong at this
		# level (the gradebook is built on top of us); we could
		# use a level of indirection through subscribers to veto this,
		# but because we think (but haven't measured!) that this is probably
		# speed critical, we're doing it the cheap, sloppy way to start with.
		# (If we're going to get externalized, and we probably are, the grade
		# object is going to get used to decorate us with anyway)
		if self._has_grade:
			return False

		# Well, blow me down, we seem to have made it!
		return True

	@property
	def __acl__(self):
		"""
		Our ACL allows read access for the creator and read/write access
		for the instructors of the course. If the student has the nuclear
		reset capability for this assignment, the student also gets
		DELETE access.
		"""
		course = ICourseInstance(self, None)
		instructors = getattr(course, 'instructors', ()) # already principals
		aces = [ace_allowing( self.creator, ACT_READ, UsersCourseAssignmentHistoryItem )]
		if self._student_nuclear_reset_capable:
			aces.append( ace_allowing(self.creator, ACT_DELETE, UsersCourseAssignmentHistoryItem) )
		for instructor in instructors:
			aces.append( ace_allowing(instructor, ALL_PERMISSIONS, UsersCourseAssignmentHistoryItem) )
		aces.append(ACE_DENY_ALL)
		return acl_from_aces( aces )

	def sublocations(self):
		if self.Submission is not None:
			yield self.Submission

		if self.pendingAssessment is not None:
			yield self.pendingAssessment

		if 'Feedback' in self.__dict__:
			yield self.Feedback

from nti.dataserver.links import Link
from nti.externalization.oids import to_external_ntiid_oid

@interface.implementer(IUsersCourseAssignmentHistoryItemSummary,
					   IACLProvider)
@component.adapter(IUsersCourseAssignmentHistoryItem)
class UsersCourseAssignmentHistoryItemSummary(Contained):
	"""
	Implements an external summary of the history by delegating to the history
	itself.
	"""
	__external_can_create__ = False

	__slots__ = (b'_history_item',)

	def __init__(self, history_item):
		self._history_item = history_item

	def __reduce__(self):
		raise TypeError()

	def __conform__(self, iface):
		return iface(self._history_item, None)

	def __acl__(self):
		return self._history_item.__acl__

	@property
	def __parent__(self):
		return self._history_item.__parent__

	@property
	def creator(self):
		return self._history_item.creator

	@property
	def assignmentId(self):
		return self._history_item.assignmentId

	@property
	def createdTime(self):
		return self._history_item.createdTime

	@property
	def lastModified(self):
		return self._history_item.lastModified

	@property
	def SubmissionCreatedTime(self):
		try:
			return self._history_item.Submission.createdTime
		except AttributeError:
			# Tests may not have a submission
			return 0.0

	@property
	def links(self):
		return (Link(self._history_item, rel='UsersCourseAssignmentHistoryItem'),)

	# Direct everything else (non-interface) to the history item
	def __getattr__(self, name):
		if name.startswith('_p_'): # pragma: no cover
			raise AttributeError(name)
		if name == 'NTIID' or name == 'ntiid': # pragma: no cover
			raise AttributeError(name)
		return getattr(self._history_item, name)

	def to_external_ntiid_oid(self):
		"""
		For convenience of the gradebook views, we match OIDs during externalization.
		This isn't really correct from a model perspective.
		"""
		return to_external_ntiid_oid(self._history_item)

from .adapters import _history_for_user_in_course

def move_user_assignment_from_course_to_course(user, old_course, new_course,
											   verbose=True):
	old_history = _history_for_user_in_course(old_course, user)
	new_history = _history_for_user_in_course(new_course, user)
	for k in list(old_history): # we are changing
		item = old_history[k]
		
		## JAM: do a full delete/re-add so that ObjectAdded event gets fired, 
		## because that's where auto-grading takes place
		del old_history[k]
		assert item.__name__ is None
		assert item.__parent__ is None
		
		if k in new_history:
			if verbose:
				logger.info("Skipped moving %s for %s from %s to %s", k, user, 
							old_course.__name__, new_course.__name__)
			continue

		new_history[k] = item
		if verbose:
			logger.info("Moved %s for %s from %s to %s", k, user,
						old_course.__name__, new_course.__name__)
