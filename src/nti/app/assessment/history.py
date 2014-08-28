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

from nti.assessment.interfaces import IQAssignmentPolicies
from nti.assessment.interfaces import IQAssignmentDateContext
from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IUser
from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer

from nti.schema.field import SchemaConfigured
from nti.schema.fieldproperty import createDirectFieldProperties

from nti.utils.property import alias
from nti.utils.property import CachedProperty

from nti.wref.interfaces import IWeakRef

from nti.zodb.minmax import NumericMaximum
from nti.zodb.minmax import NumericPropertyDefaultingToZero

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistories
from .interfaces import IUsersCourseAssignmentHistoryItem
from .interfaces import IUsersCourseAssignmentHistoryItemSummary
from .feedback import UsersCourseAssignmentHistoryItemFeedbackContainer

from nti.dataserver.authorization import ACT_READ
from nti.dataserver.authorization import ACT_DELETE
from nti.dataserver.interfaces import ACE_DENY_ALL
from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.interfaces import ALL_PERMISSIONS
from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces


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
		submission.__parent__ = item
		pending.__parent__ = item

		# The constituent parts of these things need
		# parents as well.
		# XXX It would be nice if externalization took care of this,
		# but that would be a bigger change
		def _parent( child, parent ):
			if hasattr(child, '__parent__') and child.__parent__ is None:
				child.__parent__ = parent


		for qs_sub_part in submission.parts:
			_parent( qs_sub_part, submission )
			for q_sub_part in qs_sub_part.questions:
				_parent( q_sub_part, qs_sub_part )
				for qp_sub_part in q_sub_part.parts:
					_parent( qp_sub_part, q_sub_part )


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

	@CachedProperty
	def _student_nuclear_reset_capable(self):
		"""
		Nuclear reset capability is defined by:

		#. The ``student_nuclear_reset_capable`` policy flag being true;
		#. The current date being *before* the due date;
		#. The absence of feedback;
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

		policies = IQAssignmentPolicies(course)

		policy = policies.getPolicyForAssignment(asg_id)
		if policy.get('student_nuclear_reset_capable', False):
			# Not allowed!
			return False

		dates = IQAssignmentDateContext(course)
		due_date = dates.of(assignment).available_for_submission_ending
		if due_date and datetime.utcnow() >= due_date:
			# past due
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
