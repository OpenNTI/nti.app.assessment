#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
External object decorators having to do with assessments.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.appserver import interfaces as app_interfaces

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment import interfaces as asm_interfaces

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.externalization.singleton import SingletonDecorator
from nti.externalization import interfaces as ext_interfaces
from nti.externalization.externalization import to_external_object

from .interfaces import get_course_assignment_predicate_for_user

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
@component.adapter(app_interfaces.IContentUnitInfo)
class _ContentUnitAssessmentItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

	def _predicate(self, context, result_map):
		return (AbstractAuthenticatedRequestAwareDecorator._predicate(self,context,result_map)
				and context.contentUnit is not None)

	def _do_decorate_external( self, context, result_map ):
		# When we return page info, we return questions
		# for all of the embedded units as well
		def same_file(unit1, unit2):
			try:
				return unit1.filename.split('#',1)[0] == unit2.filename.split('#',1)[0]
			except (AttributeError,IndexError):
				return False

		def recur(unit, accum):
			if same_file( unit, context.contentUnit ):
				try:
					qs = asm_interfaces.IQAssessmentItemContainer( unit, () )
				except TypeError:
					qs = ()

				accum.update( {q.ntiid: q for q in qs} )

				for child in unit.children:
					recur( child, accum )

		result = dict()
		recur( context.contentUnit, result )
		# Filter out things they aren't supposed to see...currently only
		# assignments...we can only do this if we have a user and a course
		user = self.remoteUser

		course = ICourseInstance(context.contentUnit, None)
		qsids_to_strip = set()
		if course is not None:
			assignment_predicate = get_course_assignment_predicate_for_user(user, course)
		else:
			# Only things in context of a course should have assignments
			assignment_predicate = None

		new_result = {}
		for ntiid, x in result.iteritems():
			# To keep size down, when we send back assignments or question sets,
			# we don't send back the things they contain as top-level. Moreover,
			# for assignments we need to apply a visibility predicate to the assignment
			# itself.
			if IQuestionSet.providedBy(x):
				new_result[ntiid] = x
				# XXX: Despite the above, we actually cannot yet filter
				# out duplicates from plain question sets, released iPad code
				# depends on them being there.
				#for question in x.questions:
				#	qsids_to_strip.add(question.ntiid)
			elif IQAssignment.providedBy(x):
				if assignment_predicate is None:
					logger.warn("Found assignment (%s) outside of course context in %s; dropping",
								x, context.contentUnit)
				elif assignment_predicate(x):
					# Yay, keep the assignment
					new_result[ntiid] = x
				# But in all cases, don't echo back the things
				# it contains as top-level items.
				# We are assuming that these are on the same page
				# for now and that they are only referenced by
				# this assignment.
				# XXX FIXME Bad limitation
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
			### XXX We need to be sure we don't send back the
			# solutions and explanations right now. This is
			# done in a very hacky way, need something more
			# context sensitive (would the named externalizers
			# work here? like personal-summary for users?)
			# XXX Temp disabled again pending iPad work
			def _strip(item):
				cls = item.get('Class')
				if cls == 'Question':
					for part in item['parts']:
						part['solutions'] = None
						part['explanation'] = None
				elif cls == 'QuestionSet':
					for q in item['questions']:
						_strip(q)

			ext_items = to_external_object( result )
			#for item in ext_items:
			#	_strip(item)
			result_map['AssessmentItems'] = ext_items

LINKS = ext_interfaces.StandardExternalFields.LINKS
from nti.dataserver.links import Link

from zope.location.interfaces import ILocationInfo

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

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
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

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
class _AssignmentsByOutlineNodeDecorator(_AbstractTraversableLinkDecorator):
	"""
	For things that have a assignments, add this
	as a link.
	"""

	# Note: This overlaps with the registrations in assessment_views
	# Note: We do not specify what we adapt, there are too many
	# things with no common ancestor.

	def _do_decorate_external( self, context, result_map ):
		links = result_map.setdefault( LINKS, [] )
		for rel in 'AssignmentsByOutlineNode', 'NonAssignmentAssessmentItemsByOutlineNode':
			links.append( Link( context,
								rel=rel,
								elements=(rel,)) )


from .interfaces import IUsersCourseAssignmentHistoryItemFeedback

@interface.implementer(ext_interfaces.IExternalMappingDecorator)
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


from .assessment_views import AssignmentSubmissionBulkFileDownloadView

class _AssignmentWithFilePartDownloadLinkDecorator(AbstractAuthenticatedRequestAwareDecorator):
	"""
	When an instructor feteches an assignment that contains a file part
	somewhere, provide access to the link do download it.
	"""

	def _predicate(self, context, result):
		if AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result):
			return AssignmentSubmissionBulkFileDownloadView._precondition(context, self.request, self.remoteUser) # XXX Hack

	def _do_decorate_external(self, context, result):
		links = result.setdefault( LINKS, [] )
		links.append( Link( context,
							rel='ExportFiles',
							elements=('BulkFilePartDownload',) ) )

from datetime import datetime
from nti.contenttypes.courses.interfaces import is_instructed_by_name
from nti.assessment.interfaces import IQAssignmentDateContext

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
			course = component.queryMultiAdapter( (context, remoteUser),
												  ICourseInstance)
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

		if is_instructed_by_name(course, request.authenticated_userid):
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
