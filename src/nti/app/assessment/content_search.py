#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface
from zope import lifecycleevent
from zope.securitypolicy.interfaces import IPrincipalRoleMap

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IEntity

from nti.externalization.oids import to_external_ntiid_oid

from nti.contentsearch.search_hits import SearchHit
from nti.contentsearch.interfaces import IACLResolver
from nti.contentsearch.interfaces import ICreatorResolver
from nti.contentsearch.interfaces import IUserDataSearchHit
from nti.contentsearch.interfaces import ISearchHitPredicate
from nti.contentsearch.interfaces import ISearchTypeMetaData
from nti.contentsearch.interfaces import ContentMixinResolver
from nti.contentsearch.content_utils import resolve_content_parts
from nti.contentsearch.search_metadata import SearchTypeMetaData

from nti.contenttypes.courses.interfaces import RID_TA
from nti.contenttypes.courses.interfaces import RID_INSTRUCTOR
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseInstanceAvailableEvent

from nti.dataserver.traversal import find_interface

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItem
from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

assignmentfeedback_ = u'assignmentfeedback'
ASSIGNMENT_FEEDBACK_ITEM = u'AssignmentFeedbackItem'
ASSIGNMENT_FEEDBACK_ITEM_MIMETYPE = u'application/vnd.nextthought.assignmentfeedbacktem'

class IAssignmentFeedbackItemResolver(ContentMixinResolver,
								  	  ICreatorResolver,
								  	  IACLResolver):
	pass

class IAssignmentFeedbackItemSearchHit(IUserDataSearchHit):
	pass

@interface.implementer(IAssignmentFeedbackItemResolver)
class _AssignmentFeedbackItemResolver(object):

	__slots__ = ('obj',)

	def __init__(self, obj):
		self.obj = obj

	@property
	def type(self):
		return assignmentfeedback_ # Stored type
	
	@property
	def content(self):
		return resolve_content_parts(self.obj.body)

	@property
	def containerId(self):
		parent = self.obj.__parent__
		result = to_external_ntiid_oid(parent) if parent is not None else None
		return result

	@property
	def ntiid(self):
		result = to_external_ntiid_oid(self.obj)
		return result

	@property
	def creator(self):
		result = self.obj.creator
		if IEntity.providedBy(result):
			result = unicode(result.username)
		return unicode(result) if result else None

	@property
	def lastModified(self):
		return self.obj.lastModified
	
	@property
	def createdTime(self):
		return self.obj.createdTime

	@property
	def acl(self):
		result = set()
		creator = self.creator
		if creator: # check just in case
			result.add(self.creator.lower())
		course = find_interface(self.obj, ICourseInstance, strict=False)
		role_map = IPrincipalRoleMap(course, None) 
		if role_map is not None:
			settings = role_map.getPrincipalsForRole(RID_INSTRUCTOR) or ()
			result.update(x[0].lower() for x in settings)
			
			settings = role_map.getPrincipalsForRole(RID_TA) or ()
			result.update(x[0].lower() for x in settings)
		return list(result) if result else None

@interface.implementer(IAssignmentFeedbackItemSearchHit)
class AssignmentFeedbackItemSearchHit(SearchHit):

	adapter_interface = IAssignmentFeedbackItemResolver

	def set_hit_info(self, original, score):
		adapted = super(AssignmentFeedbackItemSearchHit, self).set_hit_info(original, score)
		self.Type = ASSIGNMENT_FEEDBACK_ITEM
		self.TargetMimeType = ASSIGNMENT_FEEDBACK_ITEM_MIMETYPE
		return adapted

@interface.implementer(ISearchTypeMetaData)
def _assignmentfeedbackitem_metadata():
	## IUsersCourseAssignmentHistoryItemFeedback does not have a mime type
	## then let's assign one for it
	return SearchTypeMetaData(Name=assignmentfeedback_,
							  MimeType=ASSIGNMENT_FEEDBACK_ITEM_MIMETYPE,
							  IsUGD=True,
							  Order=99,
							  Interface=IUsersCourseAssignmentHistoryItemFeedback)

@interface.implementer(ISearchHitPredicate)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _AssignmentFeedbackItemSearchHitPredicate(object):

	def __init__(self, *args):
		pass
		
	def allow(self, feedback, score, query=None):
		result = True # by default allow
		course = find_interface(feedback, ICourseInstance, strict=False)
		item = find_interface(feedback, IUsersCourseAssignmentHistoryItem, strict=False)
		user = IUser(item, None) # get the user enrolled
		if course is not None and user is not None:
			enrollments = ICourseEnrollments(course)
			result = enrollments.get_enrollment_for_principal(user) is not None
			if not result:
				logger.debug("Item not allowed for search. %s", feedback)
		return result
	
@component.adapter(ICourseInstanceAvailableEvent)
def on_course_instance_available(event):
	course = event.object
	enrollments = ICourseEnrollments(course)
	for record in enrollments.iter_enrollments():
		principal = record.Principal
		
		## get assignment history
		assignment_history = component.queryMultiAdapter((course, principal),
														 IUsersCourseAssignmentHistory)
		if not assignment_history:
			continue
		
		for item in assignment_history.values():
			if not item.has_feedback():
				continue
			for feedback in item.Feedback.values():
				## force a reindex of the feedback object
				lifecycleevent.modified(feedback)
