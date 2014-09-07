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

from pyramid.traversal import find_interface

from nti.dataserver.interfaces import IEntity

from nti.externalization.oids import to_external_ntiid_oid

from nti.mimetype.mimetype import MIME_BASE

from nti.contentsearch.search_hits import SearchHit
from nti.contentsearch.interfaces import IACLResolver
from nti.contentsearch.interfaces import ICreatorResolver
from nti.contentsearch.interfaces import IUserDataSearchHit
from nti.contentsearch.interfaces import ISearchTypeMetaData
from nti.contentsearch.interfaces import ContentMixinResolver
from nti.contentsearch.content_utils import resolve_content_parts
from nti.contentsearch.search_metadata import SearchTypeMetaData

from nti.contenttypes.courses.interfaces import RID_TA
from nti.contenttypes.courses.interfaces import RID_INSTRUCTOR
from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments
from nti.contenttypes.courses.interfaces import ICourseInstanceAvailableEvent

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

assignmentfeedback_ = u'assignmentfeedback'
ASSIGNMENT_FEEDBACK = u'AssignmentFeedback'
ASSIGNMENT_FEEDBACK_MIMETYPE = unicode(MIME_BASE + "." + assignmentfeedback_)

class IAssignmentFeedbackResolver(ContentMixinResolver,
								  ICreatorResolver,
								  IACLResolver):
	pass

class IAssignmentFeedbackSearchHit(IUserDataSearchHit):
	pass

@interface.implementer(IAssignmentFeedbackResolver)
class _AssignmentFeedbackResolver(object):

	__slots__ = ('obj',)

	def __init__(self, obj):
		self.obj = obj

	@property
	def type(self):
		return assignmentfeedback_
	
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
		course = find_interface(self.obj, ICourseInstance)
		role_map = IPrincipalRoleMap(course, None) 
		if role_map is not None:
			principals = role_map.getPrincipalsForRole(RID_INSTRUCTOR) or ()
			result.update(instructor.id.lower() for instructor in principals)
			
			principals = role_map.getPrincipalsForRole(RID_TA) or ()
			result.update(instructor.id.lower() for instructor in principals)
		# return
		return list(result) if result else None

@interface.implementer(IAssignmentFeedbackSearchHit)
class _AssignmentFeedbackSearchHit(SearchHit):

	adapter_interface = IAssignmentFeedbackResolver

	def set_hit_info(self, original, score):
		adapted = super(_AssignmentFeedbackSearchHit, self).set_hit_info(original, score)
		self.Type = ASSIGNMENT_FEEDBACK
		self.TargetMimeType = ASSIGNMENT_FEEDBACK_MIMETYPE
		return adapted

@interface.implementer(ISearchTypeMetaData)
def _assignmentfeedback_metadata():
	## IUsersCourseAssignmentHistoryItemFeedback does not have a mime type
	## then let's assign one for it
	return SearchTypeMetaData(Name=assignmentfeedback_,
							  MimeType=ASSIGNMENT_FEEDBACK_MIMETYPE,
							  IsUGD=True,
							  Order=99,
							  Interface=IUsersCourseAssignmentHistoryItemFeedback)


@component.adapter(ICourseInstanceAvailableEvent)
def on_course_instance_available(event):
	course = event.object
	enrollments = ICourseEnrollments(course)
	for principal in enrollments.iter_enrollments():
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
