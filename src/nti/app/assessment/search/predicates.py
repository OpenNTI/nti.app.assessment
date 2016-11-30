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

from nti.assessment.interfaces import IQEvaluation

from nti.contentlibrary.interfaces import IContentPackage

from nti.contentsearch.interfaces import ISearchHitPredicate
from nti.contentsearch.predicates import DefaultSearchHitPredicate

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.contenttypes.courses.utils import is_enrolled
from nti.contenttypes.courses.utils import is_instructed_by_name
from nti.contenttypes.courses.utils import get_courses_for_packages

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

@component.adapter(IQEvaluation)
@interface.implementer(ISearchHitPredicate)
class _EvaluationSearchHitPredicate(DefaultSearchHitPredicate):

	def allow(self, item, score, query=None):
		if self.principal is None:
			return True
		else:
			course = find_interface(item, ICourseInstance, strict=False)
			if course is not None:
				courses = (course,)
			else:
				package = find_interface(item, IContentPackage, strict=False)
				if package is not None:
					courses = get_courses_for_packages(packages=package.ntiid)
				else:
					courses = ()
			
			for course in courses:
				if 		is_instructed_by_name(course, self.principal.id) \
					or	is_enrolled(course, self.principal):
					return True
		return False
