#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Storage for assignment histories.

.. note:: Even though these are adapters and so might have gone in the
  :mod:`adapters` module, they are also persistent, and as such deserve their
  own module.

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope import lifecycleevent
from zope.container.contained import Contained
from zope.cachedescriptors.property import Lazy

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.utils.property import alias
from nti.utils.schema import SchemaConfigured
from nti.utils.schema import createDirectFieldProperties

from nti.dataserver.containers import CheckingLastModifiedBTreeContainer
from nti.dataserver.containers import CaseInsensitiveCheckingLastModifiedBTreeContainer
from nti.dataserver.datastructures import PersistentCreatedModDateTrackingObject

from nti.dataserver.interfaces import IUser

from nti.wref.interfaces import IWeakRef

from nti.zodb.minmax import NumericMaximum
from nti.zodb.minmax import NumericPropertyDefaultingToZero

from .interfaces import IUsersCourseAssignmentHistories
from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItem
from .interfaces import IUsersCourseAssignmentHistoryItemSummary
from .feedback import UsersCourseAssignmentHistoryItemFeedbackContainer

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

	lastViewed = NumericPropertyDefaultingToZero('lastViewed', NumericMaximum, as_number=True)

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


from nti.dataserver.authorization import ACT_READ
from nti.dataserver.interfaces import IACLProvider
from nti.dataserver.authorization_acl import acl_from_aces
from nti.dataserver.authorization_acl import ace_allowing
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
	def __acl__(self):
		"Our ACL allows access for the creator as well as inherited permissions from the course"
		return acl_from_aces( ace_allowing( self.creator, ACT_READ, UsersCourseAssignmentHistoryItem ) )

	def sublocations(self):
		if self.Submission is not None:
			yield self.Submission
		if self.pendingAssessment is not None:
			yield self.pendingAssessment

		if 'Feedback' in self.__dict__:
			yield self.Feedback

from nti.dataserver.links import Link

@interface.implementer(IUsersCourseAssignmentHistoryItemSummary,
					   IACLProvider)
@component.adapter(IUsersCourseAssignmentHistoryItem)
class UsersCourseAssignmentHistoryItemSummary(Contained):
	"""
	Implements an external summary of the history by delegating to the history
	itself.
	"""
	__external_can_create__ = False

	__slots__ = ('_history_item',)

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
	def FeedbackCount(self):
		if self._history_item.has_feedback():
			return len(self._history_item.Feedback)
		return 0

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
