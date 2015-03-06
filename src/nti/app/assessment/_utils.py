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

from zope import component
from zope import interface

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQFilePart
from nti.assessment.interfaces import IQAssignment

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized import questionbank_question_chooser

from .interfaces import ACT_DOWNLOAD_GRADES

from .common import get_course_from_assignment

_r47694_map = None
def r47694():
	"""
	in r47694 we introduced a new type of randomizer based on the sha224 hash 
	algorithm, however, we did not take into account the fact that there were
	assignments (i.e. question banks) already taken. This cause incorrect
	questions to be returned. Fortunatelly, there were few student takers,
	so we introduce this patch to force sha224 randomizer for those students/
	assessment pairs. We now use the orginal randomizer for legacy purposes
	"""
	global _r47694_map
	if _r47694_map is None:
		path = os.path.join(os.path.dirname(__file__), "hacks/r47694.json")
		with open(path, "r") as fp:
			_r47694_map = simplejson.load(fp)
	return _r47694_map
		
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

def has_question_bank(a):
	if IQAssignment.providedBy(a):
		for part in a.parts:
			if IQuestionBank.providedBy(part.question_set):
				return True
	return False

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

def copy_taken_assignment(assignment, user):
	new_parts = []
	result = copy.copy(assignment)
	for part in assignment.parts:
		new_part = copy.copy(part)
		new_parts.append(new_part)
		question_set = part.question_set
		if IQuestionBank.providedBy(question_set):
			## select questions from bank
			questions = questionbank_question_chooser(question_set, user=user)
			## make a copy of the questions. Don't mark them as non-randomized
			questions = [copy_question(x, nonrandomized=False) for x in questions]
			## create a new bank with copy so we get all properties
			new_bank = copy.copy(question_set)
			## copy question bank with new questions
			question_set = question_set.copyTo(new_bank, questions=questions)
			## mark as non randomzied so no drawing will be made
			make_nonrandomized(question_set) 
		else:
			## copy all question set. Don't mark questions them as non-randomized
			question_set = copy_questionset(question_set, nonrandomized=False)
		new_part.question_set = question_set
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

def assignment_download_precondition(context, request, remoteUser):
	username = request.authenticated_userid
	if not username:
		return False
	
	course = get_course_from_assignment(context, remoteUser)
	if course is None or not has_permission(ACT_DOWNLOAD_GRADES, course, request):
		return False

	# Does it have a file part?
	for assignment_part in context.parts:
		question_set = assignment_part.question_set
		for question in question_set.questions:
			for question_part in question.parts:
				if IQFilePart.providedBy(question_part):
					return True # TODO: Consider caching this?
	return False

from nti.dataserver.interfaces import IUsernameSubstitutionPolicy

def replace_username(username):
	policy = component.queryUtility(IUsernameSubstitutionPolicy)
	if policy is not None:
		return policy.replace(username) or username
	return username
