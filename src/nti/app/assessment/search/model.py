#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.securitypolicy.interfaces import Allow
from zope.securitypolicy.interfaces import IPrincipalRoleMap

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.contentsearch.interfaces import IACLResolver
from nti.contentsearch.interfaces import ICreatorResolver
from nti.contentsearch.interfaces import IUserDataSearchHit
from nti.contentsearch.interfaces import ISearchTypeMetaData
from nti.contentsearch.interfaces import ContentMixinResolver

from nti.contentsearch.search_hits import SearchHit
from nti.contentsearch.search_metadata import SearchTypeMetaData

from nti.contentsearch.content_utils import resolve_content_parts

from nti.contenttypes.courses.interfaces import RID_TA
from nti.contenttypes.courses.interfaces import RID_INSTRUCTOR
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.interfaces import IEntity

from nti.externalization.oids import to_external_ntiid_oid

from nti.traversal.traversal import find_interface

#: assignment feedback search type
assignmentfeedback_ = u'assignmentfeedback'

#: assignment feedback hit type
ASSIGNMENT_FEEDBACK_ITEM = u'AssignmentFeedbackItem'

#: assignment feedback mimetype
ASSIGNMENT_FEEDBACK_ITEM_MIMETYPE = u'application/vnd.nextthought.assessment.userscourseassignmenthistoryitemfeedback'

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
		return assignmentfeedback_  # Stored type

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

	@classmethod
	def get_course_principals(self, course):
		result = set()
		role_map = IPrincipalRoleMap(course, None)
		if role_map is not None:
			for role in (RID_INSTRUCTOR, RID_TA):
				settings = role_map.getPrincipalsForRole(role) or ()
				result.update(x[0].lower() for x in settings if x[1] == Allow)
		return result

	@property
	def acl(self):
		result = set()
		creator = self.creator
		if creator: # check just in case
			result.add(self.creator.lower())
		course = find_interface(self.obj, ICourseInstance, strict=False)
		result.update(self.get_course_principals(course))
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
	return SearchTypeMetaData(Name=assignmentfeedback_,
							  MimeType=ASSIGNMENT_FEEDBACK_ITEM_MIMETYPE,
							  IsUGD=True,
							  Order=99,
							  Interface=IUsersCourseAssignmentHistoryItemFeedback)
