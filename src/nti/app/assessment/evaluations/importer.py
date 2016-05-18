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
from zope import lifecycleevent

from nti.app.assessment.evaluations.utils import indexed_iter
from nti.app.assessment.evaluations.utils import register_context
# from nti.app.assessment.evaluations.utils import import_evaluation_content

from nti.app.assessment.interfaces import ICourseEvaluations

# from nti.app.products.courseware.resources.utils import get_course_filer

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS

iface_of_assessment
@interface.implementer(ICourseSectionImporter)
class EvaluationsImporter(BaseSectionImporter):

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
		return theObject

	def handle_poll(self, theObject, course):
		ntiid = theObject.ntiid
		if self.is_new(theObject, course):
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		if theObject is None:
			raise KeyError("Poll %s does not exists." % ntiid)
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
		return theObject

	def handle_evaluation(self, theObject, course):
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
		theObject.__home__ = course
		# parse content fields and load sources
		# import_evaluation_content(result, context=course, , sources=sources)
		# always register
		register_context(result)
		return result

	def process(self, context, filer):
		result = self.externalize(context, filer)
		source = self.dump(result)
		filer.save("evaluation_index.json", source,
				   contentType="application/json", overwrite=True)
		return result
