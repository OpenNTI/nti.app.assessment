#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
External object decorators having to do with assessments.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import numbers
from urllib import unquote

from zope import component
from zope import interface
from zope.location.interfaces import ILocationInfo

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver import interfaces as app_interfaces

from nti.assessment import grader_for_response
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssessedPart
from nti.assessment.interfaces import IQuestionSubmission 
from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IQRandomizedPart
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseInstanceVendorInfo

from nti.dataserver.traversal import find_interface

from nti.externalization.singleton import SingletonDecorator
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.ntiids.ntiids import is_valid_ntiid_string
from nti.ntiids.ntiids import find_object_with_ntiid

from ._utils import is_enrolled
from ._utils import check_assessment
from ._utils import copy_questionset
from ._utils import copy_questionbank
from ._utils import is_course_instructor
from ._utils import get_assessment_items_from_unit
from ._utils import AssessmentItemProxy as AssignmentProxy

from .interfaces import IUsersCourseAssignmentHistory
from .interfaces import get_course_assignment_predicate_for_user
				
@interface.implementer(IExternalMappingDecorator)
@component.adapter(app_interfaces.IContentUnitInfo)
class _ContentUnitAssessmentItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result_map):
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self,context,result_map)
				and context.contentUnit is not None)
			
	def _get_course(self, contentUnit, user):
		result = None
		course_id = self.request.params.get('course')
		course_id = unquote(course_id) if course_id else None
		if course_id and is_valid_ntiid_string(course_id):
			result = find_object_with_ntiid(course_id)
			if 	ICourseInstance.providedBy(result) and \
				not (is_enrolled(result, user) or is_course_instructor(result, user)):
				result = None
		if result is None:
			result = component.queryMultiAdapter((contentUnit, user), ICourseInstance)	
		return result		 
	
	def _do_decorate_external( self, context, result_map ):
		# When we return page info, we return questions
		# for all of the embedded units as well
		result = get_assessment_items_from_unit(context.contentUnit)
		
		# Filter out things they aren't supposed to see...currently only
		# assignments...we can only do this if we have a user and a course
		user = self.remoteUser
		qsids_to_strip = set()
		course = self._get_course(context.contentUnit, user)
		catalog_entry = ICourseCatalogEntry(course, None)
		entry_ntiid = getattr(catalog_entry, 'ntiid', None)
		if course is not None:
			assignment_predicate = get_course_assignment_predicate_for_user(user, course)
		else:
			# Only things in context of a course should have assignments
			assignment_predicate = None

		new_result = {}
		is_instructor = False if course is None else is_course_instructor(course, user)
		for ntiid, x in result.iteritems():
			
			# To keep size down, when we send back assignments or question sets,
			# we don't send back the things they contain as top-level. Moreover,
			# for assignments we need to apply a visibility predicate to the assignment
			# itself.
			
			if IQuestionBank.providedBy(x):
				x = copy_questionbank(x, is_instructor, qsids_to_strip)
				x.ntiid = ntiid
				new_result[ntiid] = x 
			elif IRandomizedQuestionSet.providedBy(x):
				x = x if not is_instructor else copy_questionset(x, True)
				x.ntiid = ntiid
				new_result[ntiid] = x 
			elif IQuestionSet.providedBy(x):
				new_result[ntiid] = x
			elif IQAssignment.providedBy(x):
				if assignment_predicate is None:
					logger.warn("Found assignment (%s) outside of course context "
								"in %s; dropping", x, context.contentUnit)
				elif assignment_predicate(x):
					# Yay, keep the assignment
					x = check_assessment(x, user, is_instructor)
					x = AssignmentProxy(x, entry_ntiid)
					new_result[ntiid] = x
				
				# But in all cases, don't echo back the things
				# it contains as top-level items.
				# We are assuming that these are on the same page
				# for now and that they are only referenced by
				# this assignment. # XXX FIXME: Bad limitation
				for assignment_part in x.parts:
					question_set = assignment_part.question_set
					qsids_to_strip.add(question_set.ntiid)
					for question in question_set.questions:
						qsids_to_strip.add(question.ntiid)
			else:
				new_result[ntiid] = x

		for bad_ntiid in qsids_to_strip:
			new_result.pop(bad_ntiid, None)
		result = new_result.values()

		if result:
			ext_items = to_external_object(result)
			result_map['AssessmentItems'] = ext_items

@component.adapter(IQAssessedPart)
class _QAssessedPartDecorator(AbstractAuthenticatedRequestAwareDecorator):
	
	def _do_decorate_external(self, context, result_map):
		course = find_interface(context, ICourseInstance, strict=False)
		if course is None or not is_course_instructor(course, self.remoteUser):
			return
		
		# extra check 
		uca_history = find_interface(context, IUsersCourseAssignmentHistory, strict=False) 
		if uca_history is not None and uca_history.creator == self.remoteUser:
			return 
		
		# find question
		assessed_question = context.__parent__
		question_id = assessed_question.questionId
		question = component.queryUtility(IQuestion, name=question_id)
		if question is None:
			return # old question?

		# find part
		try:
			index = assessed_question.parts.index(context)
			question_part = question.parts[index]
		except IndexError:
			return
		
		## CS: for instructors we no longer randomized the questions
		## since the submittedResponse is stored randomized 
		## we unshuffle it, so the instructor can see the correct answer
		if IQRandomizedPart.providedBy(question_part):
			response = context.submittedResponse
			if response is not None:
				__traceback_info__ = response, question_part
				grader = grader_for_response(question_part, response)
				assert grader is not None
				
				## CS: We need the user that submitted the question
				## in order to unshuffle the response
				creator = uca_history.creator 
				response = grader.unshuffle(response,
											user=creator, 
											context=question_part)
				ext_response = \
					response if isinstance(response, (numbers.Real, basestring)) \
					else to_external_object(response)
			else:
				ext_response = response
			result_map['submittedResponse'] = ext_response

@component.adapter(IQuestionSubmission)
class _QuestionSubmissionDecorator(AbstractAuthenticatedRequestAwareDecorator):
	
	def _do_decorate_external(self, context, result_map):
		course = find_interface(context, ICourseInstance, strict=False)
		if course is None or not is_course_instructor(course, self.remoteUser):
			return
		
		# extra check 
		uca_history = find_interface(context, IUsersCourseAssignmentHistory, strict=False) 
		if uca_history is not None and uca_history.creator == self.remoteUser:
			return 
		
		# find question
		question_id = context.questionId
		question = component.queryUtility(IQuestion, name=question_id)
		if question is None:
			return # old question?

		if question.parts != context.parts:
			logger.warn("No all question parts were submitted")

		## CS: We need the user that submitted the question
		## in order to unshuffle the response
		creator = uca_history.creator 
		parts = result_map['parts'] = []
		for question_part, sub_part in zip(question.parts, context.parts):
			# for instructors we no longer randomized the questions
			# since the submitted response is stored randomized 
			# we unshuffle it, so the instructor can see the correct answer
			if not IQRandomizedPart.providedBy(question_part):
				parts.append(to_external_object(sub_part))
			else:
				ext_sub_part = sub_part
				if sub_part is not None:
					__traceback_info__ = sub_part, question_part
					grader = grader_for_response(question_part, sub_part)
					if grader is not None:
						response = grader.unshuffle(sub_part,
													user=creator, 
													context=question_part)
					else:
						logger.warn("Part %s does not correspond submission %s",
									question_part, sub_part  )
					ext_sub_part = 	\
						response if isinstance(response, (numbers.Real, basestring)) \
						else to_external_object(response)
				parts.append(ext_sub_part)
		
from nti.app.authentication import get_remote_user

from nti.assessment.interfaces import IQAssessedQuestion
from nti.assessment.interfaces import IQPartSolutionsExternalizer

@component.adapter(IQAssessedQuestion)
class _QAssessedQuestionExplanationSolutionAdder(object):
	"""
	Because we don't generally want to provide solutions and explanations
	until after a student has submitted, we place them on the assessed object.

	.. note:: In the future this may be registered/unregistered on a site
		by site basis (where a Course is a site) so that instructor preferences
		on whether or not to provide solutions can be respected.
	"""
	
	__metaclass__ = SingletonDecorator

	def decorateExternalObject( self, context, mapping ):
		question_id = context.questionId
		question = component.queryUtility(IQuestion, name=question_id)
		if question is None:
			return # old?

		remoteUser = get_remote_user()
		course = find_interface(context, ICourseInstance, strict=False)
		is_instructor = remoteUser and course and is_course_instructor(course, remoteUser)
			
		for question_part, external_part in zip(question.parts, mapping['parts']):
			if not is_instructor:
				externalizer = IQPartSolutionsExternalizer(question_part)
				external_part['solutions'] = externalizer.to_external_object()
			else:
				external_part['solutions'] = to_external_object(question_part.solutions)
			external_part['explanation'] = to_external_object(question_part.explanation)
		
LINKS = StandardExternalFields.LINKS
from nti.dataserver.links import Link

class _AbstractTraversableLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result):
		# We only do this if we can create the traversal path to this object;
		# many times the CourseInstanceEnrollments aren't fully traversable
		# (specifically, for the course roster)
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			if context.__parent__ is None:
				return False # Short circuit
			try:
				loc_info = ILocationInfo( context )
				loc_info.getParents()
			except TypeError:
				return False
			else:
				return True

from nti.dataserver.interfaces import IUser

@interface.implementer(IExternalMappingDecorator)
class _AssignmentHistoryItemDecorator(_AbstractTraversableLinkDecorator):
	"""
	For things that have an assignment history, add this
	as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor.

	def _do_decorate_external( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		# If the context provides a user, that's the one we want,
		# otherwise we want the current user
		user = IUser(context, self.remoteUser)
		links.append( Link( context,
							rel='AssignmentHistory',
							elements=('AssignmentHistories', user.username)) )

@interface.implementer(IExternalMappingDecorator)
class _AssignmentsByOutlineNodeDecorator(_AbstractTraversableLinkDecorator):
	"""
	For things that have a assignments, add this
	as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor. Those registrations are more general,
	# though, because we try to always go through a course, if possible
	# (because of issues resolving really old enrollment records), although
	# the enrollment record is a better place to go because it has the username
	# in the path
	
	def show_links(self, course):
		"""
		Returns a true value if the course should show the links [Non] assignments 
		by outline ode links
		"""
		## TODO: We will remove when a preference course/user? policy is in place.
		vendor_info = ICourseInstanceVendorInfo(course, {})
		try:
			result = vendor_info['NTI']['show_assignments_by_outline']
		except (TypeError, KeyError):
			result = True
		return result
	
	def _do_decorate_external(self, context, result_map):
		course = ICourseInstance(context, context)
		if not self.show_links(course):
			return
		
		links = result_map.setdefault( LINKS, [] )
		for rel in ('AssignmentsByOutlineNode', 'NonAssignmentAssessmentItemsByOutlineNode'):
			# Prefer to canonicalize these through to the course, if possible
			link = Link( course,
						 rel=rel,
						 elements=(rel,),
						 # We'd get the wrong type/ntiid values if we
						 # didn't ignore them.
						 ignore_properties_of_target=True)
			links.append(link)

from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

@interface.implementer(IExternalMappingDecorator)
@component.adapter(IUsersCourseAssignmentHistoryItemFeedback)
class _FeedbackItemAssignmentIdDecorator(object):
	"""
	Give a feedback item its assignment id, because it is used
	in contexts outside its collection.
	"""

	__metaclass__ = SingletonDecorator

	def decorateExternalMapping( self, item, result_map ):
		try:
			feedback = item.__parent__
			history_item = feedback.__parent__
			submission = history_item.Submission
			result_map['AssignmentId'] = submission.assignmentId
		except AttributeError:
			pass

class _LastViewedAssignmentHistoryDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	For assignment histories, when the requester is the owner,
	we add a link to point to the 'lastViewed' update spot.
	"""

	def _predicate(self, context, result):
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result)
				and context.owner is not None
				and context.owner == self.remoteUser)

	def _do_decorate_external(self, context, result):
		links = result.setdefault( LINKS, [] )
		links.append( Link( context,
							rel='lastViewed',
							elements=('lastViewed',),
							method='PUT' ) )

from ._utils import assignment_download_precondition 

class _AssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an instructor feteches an assignment that contains a file part
	somewhere, provide access to the link do download it.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return assignment_download_precondition(context, self.request, self.remoteUser) # XXX Hack

	def _do_decorate_external(self, context, result):
		links = result.setdefault( LINKS, [] )
		links.append( Link( context,
							rel='ExportFiles',
							elements=('BulkFilePartDownload',) ) )

from datetime import datetime

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQAssignmentDateContext

from nti.contenttypes.courses.interfaces import ICourseCatalog

from .interfaces import ACT_VIEW_SOLUTIONS

def _get_course_from_assignment(assignment, user):
	## check if we have the context catalog entry we can use 
	## as reference (.adapters._QProxy) this way
	## instructor can find the correct course when they are looking
	## at a section.
	result = None
	ntiid = getattr(assignment, 'CatalogEntryNTIID', None)
	if ntiid:
		catalog = component.getUtility(ICourseCatalog)
		try:
			entry = catalog.getCatalogEntry(ntiid)
			result = ICourseInstance(entry, None)
		except KeyError:
			pass
	if result is None:	
		result = component.queryMultiAdapter((assignment, user), ICourseInstance)
	return result

class _AssignmentSectionSpecificDates(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an assignment is externalized, write the section specific dates.
	"""
		
	def _do_decorate_external(self, assignment, result):
		course = _get_course_from_assignment(assignment, self.remoteUser)
		if course is not None:
			dates = IQAssignmentDateContext(course).of(assignment)
			for k in ('available_for_submission_ending',
					  'available_for_submission_beginning'):
				asg_date = getattr(assignment, k)
				dates_date = getattr(dates, k)
				if dates_date != asg_date:
					result[k] = to_external_object(dates_date)

class _AssignmentBeforeDueDateSolutionStripper(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When anyone besides the instructor requests an assignment
	that has a due date, and we are before the due date,
	do not release the answers.

	.. note:: This is currently incomplete. We are also sending these
		question set items back 'standalone'. Depending on the UI, we
		may need to strip them there too.
	"""

	@classmethod
	def needs_stripped(cls, context, request, remoteUser):
		due_date = None
		course = None
		if context is not None:
			course = _get_course_from_assignment(context, remoteUser)
			if course is not None:
				due_date = IQAssignmentDateContext(course).of(context).available_for_submission_ending
			else:
				due_date = context.available_for_submission_ending
		if not due_date or due_date <= datetime.utcnow():
			# No due date, nothing to do
			# Past the due date, nothing to do
			return False

		if course is None:
			logger.warn("could not adapt %s to course", context)
			return False

		if has_permission(ACT_VIEW_SOLUTIONS, course, request):
			# The instructor, nothing to do
			return False

		return True

	@classmethod
	def strip(cls,item):
		_cls = item.get('Class')
		if _cls in ('Question','AssessedQuestion'):
			for part in item['parts']:
				part['solutions'] = None
				part['explanation'] = None
		elif _cls in ('QuestionSet','AssessedQuestionSet'):
			for q in item['questions']:
				cls.strip(q)

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return self.needs_stripped(context, self.request, self.remoteUser)

	def _do_decorate_external(self, context, result):
		for part in result['parts']:
			question_set = part['question_set']
			self.strip(question_set)

class _AssignmentSubmissionPendingAssessmentBeforeDueDateSolutionStripper(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When anyone besides the instructor requests an assessed part
	within an assignment that has a due date, and we are before the
	due date, do not release the answers.

	.. note:: This is currently incomplete. We are also sending these
		question set items back 'standalone'. Depending on the UI, we
		may need to strip them there too.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			assg = component.queryUtility(IQAssignment, context.assignmentId)
			return _AssignmentBeforeDueDateSolutionStripper.needs_stripped(assg, self.request, self.remoteUser)

	def _do_decorate_external(self, context, result):
		for part in result['parts']:
			_AssignmentBeforeDueDateSolutionStripper.strip(part)


class _IPad110NoSubmitPartAdjuster(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Here is a bit of background first. The CS1323 has a bunch of
	"no-submit" assignments for things that aren't submitted on the
	platform (turings craft, problets, etc). These no submit
	assignments were marked up in the content on a page titled
	"Grades" beneath each lesson that had no-submit assignments
	content nodes. Because these were no_submits the webapp handles
	clicks on them in a special way however when written in December
	the pad was not. The pad just takes you to whatever content page
	is appropriate for the assignment just like it does for "normal"
	assignments or question sets. Come January that was a problem
	because clicking the no-submit assignment on the pad just
	presented a blank page to the user. At the time, to prevent this,
	we coded up some filtering logic to filter these empty assignments
	out of the overview if they had no parts. In retrospect we should
	have just changed how we authored the content but hindsights
	always 20/20.

	This is now causing issues because they want to change all the no
	submits to actually have a content page like a normal assignment.
	Basically a page that gives the instructions on how to do the
	no-submit assignment (rather than a separate link like is used
	now). This all works fine except that these assignments have no
	parts and so they don't show up on the overview. I checked on my
	side and it seems like if I can get past the filtering things work
	just as we would expect. We obviously won't have something in the
	store come monday that works with this content so I was wondering
	if there was something we could do on the server side [1] to help
	work around this. To get past the pad's filtering these
	Assignments need to have a non-empty parts array in the response
	of the AssignmentsByOutlineNode call.

	Something like :

	parts: [{Class: AssignmentPart}]

	would do it from what I can tell.
	"""

	_BAD_UAS = ( "NTIFoundation DataLoader NextThought/1.0",
				 "NTIFoundation DataLoader NextThought/1.1.0",
				 "NTIFoundation DataLoader NextThought/1.1.1")

	def _predicate(self, context, result):
		if context.category_name != 'no_submit' or context.parts:
			return False

		ua = self.request.environ.get('HTTP_USER_AGENT', '')
		if not ua:
			return False

		for bua in self._BAD_UAS:
			if ua.startswith(bua):
				return True

	def _do_decorate_external(self, context, result):
		result['parts'] = [{'Class': 'AssignmentPart'}]
					