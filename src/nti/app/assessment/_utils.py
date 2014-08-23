#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import copy

from zope import interface
from zope.security.interfaces import IPrincipal
from zope.securitypolicy.interfaces import Allow
from zope.securitypolicy.interfaces import IPrincipalRoleMap

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contenttypes.courses.interfaces import RID_TA
from nti.contenttypes.courses.interfaces import RID_INSTRUCTOR

def has_question_bank(a):
	if IQAssignment.providedBy(a):
		for part in a.parts:
			if IQuestionBank.providedBy(part.question_set):
				return True
	return False

def is_course_instructor(course, user):
	prin = IPrincipal(user)
	roles = IPrincipalRoleMap(course, None)
	if not roles:
		return False
	return Allow in (roles.getSetting(RID_TA, prin.id),
					 roles.getSetting(RID_INSTRUCTOR, prin.id))
			
def same_content_unit_file(unit1, unit2):
	try:
		return unit1.filename.split('#',1)[0] == unit2.filename.split('#',1)[0]
	except (AttributeError, IndexError):
		return False
	
def get_assessment_items_from_unit(contentUnit):
	
	def recur(unit, accum):
		if same_content_unit_file(unit, contentUnit):
			try:
				qs = IQAssessmentItemContainer(unit, ())
			except TypeError:
				qs = ()

			accum.update( {q.ntiid: q for q in qs} )

			for child in unit.children:
				recur( child, accum )
	
	result = dict()
	recur(contentUnit, result )
	return result
			
def copy_question(q, part_marker_iface=None):
	if IQuestion.providedBy(q):
		result = copy.copy(q)
		result.parts = [copy.copy(p) for p in q.parts]
		if part_marker_iface:
			for p in result.partss:
				interface.alsoProvides(p, part_marker_iface)
		return result
	return q

def copy_questionset(qs, part_marker_iface=None):
	if IQuestionSet.providedBy(qs):
		result = copy.copy(qs)
		result.questions = [copy_question(q, part_marker_iface) for q in qs.questions]
	return qs
