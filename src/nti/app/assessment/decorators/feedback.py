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

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItemFeedback

from nti.app.contentlibrary.decorators import AbstractLibraryPathLinkDecorator

from nti.externalization.interfaces import IExternalMappingDecorator

from nti.externalization.singleton import SingletonDecorator

@interface.implementer(IExternalMappingDecorator)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _FeedbackItemAssignmentIdDecorator(object):
	"""
	Give a feedback item its assignment id, because it is used
	in contexts outside its collection.
	"""

	__metaclass__ = SingletonDecorator

	def decorateExternalMapping(self, item, result_map):
		try:
			feedback = item.__parent__
			history_item = feedback.__parent__
			submission = history_item.Submission
			creator = submission.creator
			creator = getattr( creator, 'username', creator )
			result_map['AssignmentId'] = submission.assignmentId
			result_map['SubmissionCreator'] = creator
		except AttributeError:
			pass

@interface.implementer(IExternalMappingDecorator)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _FeedbackLibraryPathLinkDecorator(AbstractLibraryPathLinkDecorator):
	pass
