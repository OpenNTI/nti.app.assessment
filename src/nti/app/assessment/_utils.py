#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import copy
import simplejson

from zope import interface
from zope.security.interfaces import IPrincipal
from zope.securitypolicy.interfaces import Allow
from zope.securitypolicy.interfaces import IPrincipalRoleMap

from nti.assessment.interfaces import IQAssignment
from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.assessment.randomized import questionbank_question_chooser

from nti.contenttypes.courses.interfaces import RID_TA
from nti.contenttypes.courses.interfaces import RID_INSTRUCTOR

_r47694_map = None
def r47694():
	"""
	in r47694 we introduced a new type of randomizer based on the sha224 hash 
	algorithm, however, we did not take into account the fact that there were
	assignments (i.e. question banks) already taken. This cause incorrect
	questing to be return. Fortunatelly, there were few takers,
	so wee introduce this patch to force sha224 randomizer as we returned to
	the orginal randomizer for legacy purposes
	"""
	global _r47694_map
	if _r47694_map is None:
		path = os.path.join(os.path.dirname(__file__), "hacks/r47694.json")
		with open(path, "r") as fp:
			_r47694_map = simplejson.load(fp)
	return _r47694_map

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

def make_sha224randomized(context):
	iface = getattr(context, 'sha224randomized_interface', None)
	if iface is not None:
		interface.alsoProvides(context, iface)
		return True
	return False

def sublocations(context):
	if hasattr(context, 'sublocations'):
		tuple(context.sublocations())
	return context

def copy_part(part, nonrandomized=False, sha224randomized=False):
	result = copy.copy(part)
	if nonrandomized:
		make_nonrandomized(result)
	elif sha224randomized:
		make_sha224randomized(result)
	return result

def copy_question(q, nonrandomized=False):
	result = copy.copy(q)
	result.parts = [copy_part(p, nonrandomized) for p in q.parts]
	if nonrandomized:
		make_nonrandomized(result)
	sublocations(result)
	return result

def copy_questionset(qs, nonrandomized=False):
	result = copy.copy(qs)
	result.questions = [copy_question(q, nonrandomized) for q in qs.questions]
	if nonrandomized:
		for question in result.questions:
			make_nonrandomized(question)
		make_nonrandomized(result)
	sublocations(result)
	return result

def copy_questionbank(bank, is_instructor=False, qsids_to_strip=None):
	if is_instructor:
		result = copy_questionset(bank, True)
	else:
		result = bank.copy(questions=questionbank_question_chooser(bank))
		if qsids_to_strip is not None:
			drawn_ntiids = {q.ntiid for q in result.questions}
			# remove any question that has not been drawn
			bank_ntiids = {q.ntiid for q in bank.questions}
			if len(bank_ntiids) != len(drawn_ntiids):
				qsids_to_strip.update(bank_ntiids.difference(drawn_ntiids))
	sublocations(result)
	return result

def copy_assessment(assessment, nonrandomized=False):
	new_parts = []
	result = copy.copy(assessment)
	for part in assessment.parts:
		new_part = copy.copy(part)
		new_part.question_set = copy_questionset(part.question_set, nonrandomized)
		new_parts.append(new_part)
	result.parts = new_parts
	sublocations(result)
	return result

def check_assessment(assessment, user=None, is_instructor=False):
	result = assessment
	if is_instructor:
		result = copy_assessment(assessment, True)
	elif user is not None:
		ntiid = assessment.ntiid
		username = user.username
		# check r47694 
		hack_map = r47694()
		if ntiid in hack_map and username in hack_map[ntiid]:
			result = copy_assessment(assessment)
			for part in result.parts:
				make_sha224randomized(part.question_set)
	return result
