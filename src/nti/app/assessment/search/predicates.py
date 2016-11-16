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

from nti.contentsearch.interfaces import ISearchHitPredicate
from nti.contentsearch.predicates import DefaultSearchHitPredicate

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_instructed_by_name

from nti.dataserver.users import User

from nti.traversal.traversal import find_interface

@interface.implementer(ISearchHitPredicate)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _AssignmentFeedbackItemSearchHitPredicate(DefaultSearchHitPredicate):

	def allow(self, feedback, score, query=None):
		if self.principal is None:
			return True
		else:
			pid = self.principal.id
			user = User.get_user(pid)
			owner = feedback.creator
			course = find_interface(feedback, ICourseInstance, strict=False)
			if 		user is not None \
				and (owner == user is not None or is_instructed_by_name(course, pid)):
				return True
		return False
