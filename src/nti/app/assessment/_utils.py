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
from zope.schema.interfaces import RequiredMissing

from zope.security.interfaces import IPrincipal
from zope.securitypolicy.interfaces import Allow
from zope.securitypolicy.interfaces import IPrincipalRoleMap

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQFilePart
from nti.assessment.interfaces import IQAssignment
from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.interfaces import IQAssessmentItemContainer
from nti.assessment.randomized import questionbank_question_chooser

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import RID_TA
from nti.contenttypes.courses.interfaces import RID_INSTRUCTOR
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.traversal import find_interface

from .interfaces import ACT_DOWNLOAD_GRADES

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

def find_course_for_assignment(assignment, user, exc=True):
	# Check that they're enrolled in the course that has the assignment
	course = component.queryMultiAdapter( (assignment, user),
										  ICourseInstance)
	if course is None:
		# For BWC, we also check to see if we can just get
		# one based on the content package of the assignment, not
		# checking enrollment.
		# TODO: Drop this
		course = ICourseInstance( find_interface(assignment, IContentPackage, strict=False),
								  None)
		if course is not None:
			logger.warning("No enrollment found, assuming generic course. Tests only?")

	# If one does not exist, we cannot grade because we have nowhere
	# to dispatch to.
	if course is None and exc:
		raise RequiredMissing("Course cannot be found")

	return course

def assignment_download_precondition(context, request, remoteUser):
	username = request.authenticated_userid
	if not username:
		return False
	
	course = find_course_for_assignment(context, remoteUser, exc=False)
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

def set_submission_lineage(submission):
	## The constituent parts of these things need parents as well.
	## XXX It would be nice if externalization took care of this,
	## but that would be a bigger change
	def _set_parent(child, parent):
		if hasattr(child, '__parent__') and child.__parent__ is None:
			child.__parent__ = parent

	for submission_set in submission.parts:
		# submission_part e.g. assessed question set
		_set_parent(submission_set, submission)
		for submitted_question in submission_set.questions:
			_set_parent(submitted_question, submission_set)
			for submitted_question_part in submitted_question.parts:
				_set_parent(submitted_question_part, submitted_question)
	return submission
