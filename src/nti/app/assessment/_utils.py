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
		
def make_nonrandomized(context):
	iface = getattr(context, 'nonrandomized_interface', None)
	if iface is not None:
		interface.alsoProvides(context, iface)
		return True
	return False

def copy_question(q, nonrandomized=False):
	result = copy.copy(q)
	result.parts = [copy.copy(p) for p in q.parts]
	if nonrandomized:
		for part in result.parts:
			make_nonrandomized(part)
		make_nonrandomized(result)
	return result

def copy_questionset(qs, nonrandomized=False):
	result = copy.copy(qs)
	result.questions = [copy_question(q, nonrandomized) for q in qs.questions]
	if nonrandomized:
		for question in result.questions:
			make_nonrandomized(question)
		make_nonrandomized(result)
	return result

def copy_assessment(assessment, nonrandomized=False):
	new_parts = []
	result = copy.copy(assessment)
	for part in assessment.parts:
		new_part = copy.copy(part)
		new_part.question_set = copy_questionset(part.question_set, 
												 nonrandomized)
		new_parts.append(new_part)
	result.parts = new_parts
	return result

