#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os

from zope import component
from zope import interface
from zope import lifecycleevent

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
from nti.app.assessment.evaluations.utils import import_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.authentication import get_remote_user

from nti.app.products.courseware.resources.utils import get_course_filer

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.cabinet.filer import transfer_to_native_file

from nti.contentlibrary.interfaces import IFilesystemBucket

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.coremetadata.interfaces import ICalendarPublishable

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

ITEMS = StandardExternalFields.ITEMS

@interface.implementer(ICourseSectionImporter)
class EvaluationsImporter(BaseSectionImporter):

	EVALUATION_INDEX = "evaluation_index.json"

	def is_new(self, obj, course):
		ntiid = obj.ntiid
		provided = iface_of_assessment(obj)
		evaluations = ICourseEvaluations(course)
		return	  ntiid not in evaluations \
				and component.queryUtility(provided, name=ntiid) is None

	def store_evaluation(self, obj, course):
		evaluations = ICourseEvaluations(course)
		lifecycleevent.created(obj)
		evaluations[obj.ntiid] = obj  # gain intid
		return obj

	def get_registered_evaluation(self, obj, course):
		ntiid = obj.ntiid
		evaluations = ICourseEvaluations(course)
		if ntiid in evaluations:  # replace
			obj = evaluations[ntiid]
		else:
			provided = iface_of_assessment(obj)
			obj = component.queryUtility(provided, name=ntiid)
		return obj

	def handle_question(self, theObject, course):
		ntiid = theObject.ntiid
		if self.is_new(theObject, course):
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise KeyError("Question %s does not exists." % ntiid)
		[p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
		return theObject

	def handle_poll(self, theObject, course):
		ntiid = theObject.ntiid
		if self.is_new(theObject, course):
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise KeyError("Poll %s does not exists." % ntiid)
		[p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
		return theObject

	def handle_question_set(self, theObject, course):
		ntiid = theObject.ntiid
		if self.is_new(theObject, course):
			questions = indexed_iter()
			for question in theObject.questions or ():
				question = self.handle_question(question, course)
				questions.append(question)
			theObject.questions = questions
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise KeyError("QuestionSet %s does not exists." % ntiid)
		return theObject

	def handle_survey(self, theObject, course):
		ntiid = theObject.ntiid
		if self.is_new(theObject, course):
			questions = indexed_iter()
			for poll in theObject.questions or ():
				poll = self.handle_poll(poll, course)
				questions.append(poll)
			theObject.questions = questions
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise KeyError("Survey %s does not exists." % ntiid)
		return theObject

	def handle_assignment_part(self, part, course):
		question_set = self.handle_question_set(part.question_set, course)
		part.question_set = question_set
		return part

	def handle_assignment(self, theObject, course):
		ntiid = theObject.ntiid
		if self.is_new(theObject, course):
			parts = indexed_iter()
			for part in theObject.parts or ():
				part = self.handle_assignment_part(part, course)
				parts.append(part)
			theObject.parts = parts
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise KeyError("Assignment %s does not exists." % ntiid)
		[p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
		return theObject

	def handle_evaluation(self, theObject, course, source_filer):
		if IQuestion.providedBy(theObject):
			result = self.handle_question(theObject, course)
		elif IQPoll.providedBy(theObject):
			result = self.handle_poll(theObject, course)
		elif IQuestionSet.providedBy(theObject):
			result = self.handle_question_set(theObject, course)
		elif IQSurvey.providedBy(theObject):
			result = self.handle_survey(theObject, course)
		elif IQAssignment.providedBy(theObject):
			result = self.handle_assignment(theObject, course)
		else:
			result = theObject

		# course is the evaluation home
		result.__home__ = course
		remoteUser = get_remote_user()
		target_filer = get_course_filer(course, remoteUser)

		# parse content fields and load sources
		import_evaluation_content(result, source_filer=source_filer,
								  target_filer=target_filer)

		# always register
		register_context(result)

		# always publish
		if not result.is_published():
			if ICalendarPublishable.providedBy(result):
				result.publish(start=result.publishBeginning,
							   end=result.publishEnding,
							   event=False)
			else:
				result.publish(event=False)
		return result

	def handle_course_items(self, items, course, source_filer):
		for ext_obj in items or ():
			factory = find_factory_for(ext_obj)
			theObject = factory()
			update_from_external_object(theObject, ext_obj, notify=False)
			self.handle_evaluation(theObject, course, source_filer)

	def do_import(self, course, filer, writeout=True):
		href = self.course_bucket_path(course) + self.EVALUATION_INDEX
		source = self.safe_get(filer, href)
		if source is not None:
			source = self.load(source)
			items = source.get(ITEMS)
			self.handle_course_items(items, course, filer)
			# save source
			if writeout and IFilesystemBucket.providedBy(course.root):
				source = self.safe_get(filer, href)  # reload
				self.makedirs(course.root.absolute_path)  # create
				new_path = os.path.join(course.root.absolute_path, self.EVALUATION_INDEX)
				transfer_to_native_file(source, new_path)
			return True
		return False

	def process(self, context, filer, writeout=True):
		course = ICourseInstance(context)
		result = self.do_import(course, filer, writeout)
		for subinstance in get_course_subinstances(course):
			result = self.do_import(subinstance, filer, writeout) or result
		return result
