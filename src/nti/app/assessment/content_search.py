#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Search content utilities.

$Id$
"""
from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from pyramid.traversal import find_interface

from nti.dataserver import interfaces as nti_interfaces

from nti.externalization.oids import to_external_ntiid_oid

from nti.mimetype.mimetype import MIME_BASE

from nti.contentsearch import content_utils
from nti.contentsearch.search_hits import SearchHit
from nti.contentsearch import interfaces as search_interfaces
from nti.contentsearch.search_metadata import SearchTypeMetaData
from nti.contentsearch.constants import CONTAINER_ID, TYPE, TARGET_MIME_TYPE

from nti.contenttypes.courses.interfaces import ICourseInstance

from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

assignmentfeedback_ = u'assignmentfeedback'
ASSIGNMENT_FEEDBACK = u'AssignmentFeedback'
ASSIGNMENT_FEEDBACK_MIMETYPE = unicode(MIME_BASE + "." + assignmentfeedback_)

class IAssignmentFeedbackResolver(search_interfaces.IACLResolver,
								  search_interfaces.ITypeResolver,
								  search_interfaces.IContentResolver,
								  search_interfaces.INTIIDResolver,
								  search_interfaces.ICreatorResolver,
								  search_interfaces.ILastModifiedResolver,
								  search_interfaces.ICreatedTimeResolver):
	pass

class IAssignmentFeedbackSearchHit(search_interfaces.ISearchHit):
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
		return content_utils.resolve_content_parts(self.obj.body)

	@property
	def ntiid(self):
		result = to_external_ntiid_oid(self.obj)
		return result

	@property
	def creator(self):
		result = self.obj.creator
		if nti_interfaces.IEntity.providedBy(result):
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
		if creator:
			result.add(self.creator.lower())
		course = find_interface(self.obj, ICourseInstance)
		if course is not None:
			# XXX The instructors are static if we allow changing instructors
			# this ACL will be come invalid
			result.update([instructor.id.lower() for instructor in course.instructors])
		return list(result) if result else None

@interface.implementer(IAssignmentFeedbackSearchHit)
class _AssignmentFeedbackSearchHit(SearchHit):

	adapter_interface = IAssignmentFeedbackResolver

	def set_hit_info(self, original, score):
		adapted = super(_AssignmentFeedbackSearchHit, self).set_hit_info(original, score)
		self[TYPE] = ASSIGNMENT_FEEDBACK
		self[TARGET_MIME_TYPE] = ASSIGNMENT_FEEDBACK_MIMETYPE
		self.pop(CONTAINER_ID, None)  # remove container id
		return adapted

@interface.implementer(search_interfaces.ISearchTypeMetaData)
def _assignmentfeedback_metadata():
	# IUsersCourseAssignmentHistoryItemFeedback does not have a mime type
	# then let's assign one for it
	return SearchTypeMetaData(Name=assignmentfeedback_,
							  MimeType=ASSIGNMENT_FEEDBACK_MIMETYPE,
							  IsUGD=True, Order=99,
							  Interface=IUsersCourseAssignmentHistoryItemFeedback)

