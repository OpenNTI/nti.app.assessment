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
import uuid

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.security.interfaces import IPrincipal

from nti.app.assessment.common import make_evaluation_ntiid

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
from nti.assessment.interfaces import IQEditableEvaluation

from nti.cabinet.filer import transfer_to_native_file

from nti.coremetadata.utils import currentPrincipal

from nti.contentlibrary.interfaces import IFilesystemBucket

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.contenttypes.courses.importer import BaseSectionImporter

from nti.contenttypes.courses.utils import get_course_subinstances

from nti.coremetadata.interfaces import IRecordable
from nti.coremetadata.interfaces import ICalendarPublishable

from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import find_factory_for
from nti.externalization.internalization import update_from_external_object

from nti.property.property import Lazy

ITEMS = StandardExternalFields.ITEMS


@interface.implementer(ICourseSectionImporter)
class EvaluationsImporter(BaseSectionImporter):

	EVALUATION_INDEX = "evaluation_index.json"

	@property
	def _extra(self):
		return str(uuid.uuid4()).split('-')[0].upper()

	@Lazy
	def current_principal(self):
		remoteUser = IPrincipal(get_remote_user(), None)
		if remoteUser is None:
			remoteUser = currentPrincipal()
		return remoteUser

	def get_ntiid(self, obj):
		return getattr(obj, 'ntiid', None)

	def is_new(self, obj, course):
		ntiid = self.get_ntiid(obj)
		provided = iface_of_assessment(obj)
		evaluations = ICourseEvaluations(course)
		return		not ntiid \
			or (	ntiid not in evaluations
				 and component.queryUtility(provided, name=ntiid) is None)

	def store_evaluation(self, obj, course):
		principal = self.current_principal
		ntiid = self.get_ntiid(obj)
		if not ntiid:
			provided = iface_of_assessment(obj)
			obj.ntiid = make_evaluation_ntiid(provided, extra=self._extra)
		obj.creator = principal.id  # always seet a creator
		evaluations = ICourseEvaluations(course)
		lifecycleevent.created(obj)
		evaluations[obj.ntiid] = obj  # gain intid
		interface.alsoProvides(obj, IQEditableEvaluation)  # mark as editable
		return obj

	def get_registered_evaluation(self, obj, course):
		ntiid = self.get_ntiid(obj)
		evaluations = ICourseEvaluations(course)
		if ntiid in evaluations:  # replace
			old = evaluations[ntiid]
			obj = evaluations.replace(old, obj, event=False)
		else:
			provided = iface_of_assessment(obj)
			obj = component.queryUtility(provided, name=ntiid)
		return obj

	def handle_question(self, theObject, course):
		if self.is_new(theObject, course):
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		[p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
		return theObject

	def handle_poll(self, theObject, course):
		if self.is_new(theObject, course):
			theObject = self.store_evaluation(theObject, course)
		else:
			theObject = self.get_registered_evaluation(theObject, course)
		[p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
		return theObject

	def handle_question_set(self, theObject, course):
		if not self.is_new(theObject, course):
			theObject = self.get_registered_evaluation(theObject, course)
		questions = indexed_iter()
		for question in theObject.questions or ():
			question = self.handle_question(question, course)
			questions.append(question)
		theObject.questions = questions
		theObject = self.store_evaluation(theObject, course)
		return theObject

	def handle_survey(self, theObject, course):
		if not self.is_new(theObject, course):
			theObject = self.get_registered_evaluation(theObject, course)
		questions = indexed_iter()
		for poll in theObject.questions or ():
			poll = self.handle_poll(poll, course)
			questions.append(poll)
		theObject.questions = questions
		theObject = self.store_evaluation(theObject, course)
		return theObject

	def handle_assignment_part(self, part, course):
		question_set = self.handle_question_set(part.question_set, course)
		part.question_set = question_set
		return part

	def handle_assignment(self, theObject, course):
		if not self.is_new(theObject, course):
			theObject = self.get_registered_evaluation(theObject, course)
		parts = indexed_iter()
		for part in theObject.parts or ():
			part = self.handle_assignment_part(part, course)
			parts.append(part)
		theObject.parts = parts
		theObject = self.store_evaluation(theObject, course)
		[p.ntiid for p in theObject.parts or ()]  # set auto part NTIIDs
		return theObject

	def handle_evaluation(self, theObject, source, course, source_filer=None):
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

		if IQEditableEvaluation.providedBy(result):
			# course is the evaluation home
			result.__home__ = course
			remoteUser = get_remote_user()
			target_filer = get_course_filer(course, remoteUser)
			# parse content fields and load sources
			import_evaluation_content(result, 
									  context=course, 
									  source_filer=source_filer,
									  target_filer=target_filer)
			# always register
			register_context(result, force=True)

		isPublished = source.get('isPublished')
		if isPublished:
			if ICalendarPublishable.providedBy(result):
				result.publish(start=result.publishBeginning,
							   end=result.publishEnding,
							   event=False)
			else:
				result.publish(event=False)

		locked = source.get('isLocked')
		if locked and IRecordable.providedBy(theObject):
			theObject.lock(event=False)
			lifecycleevent.modified(theObject)
		return result

	def handle_course_items(self, items, course, source_filer=None):
		for ext_obj in items or ():
			source = copy.deepcopy(ext_obj)
			factory = find_factory_for(ext_obj)
			theObject = factory()
			update_from_external_object(theObject, ext_obj, notify=False)
			self.handle_evaluation(theObject, source, course, source_filer)

	def process_source(self, course, source, filer=None):
		source = self.load(source)
		items = source.get(ITEMS)
		self.handle_course_items(items, course, filer)
			
	def do_import(self, course, filer, writeout=True):
		href = self.course_bucket_path(course) + self.EVALUATION_INDEX
		source = self.safe_get(filer, href)
		if source is not None:
			self.process_source(course, source, filer)
			# save source
			if writeout and IFilesystemBucket.providedBy(course.root):
				source = self.safe_get(filer, href)  # reload
				self.makedirs(course.root.absolute_path)  # create
				new_path = os.path.join(course.root.absolute_path,
										self.EVALUATION_INDEX)
				transfer_to_native_file(source, new_path)
			return True
		return False

	def process(self, context, filer, writeout=True):
		course = ICourseInstance(context)
		result = self.do_import(course, filer, writeout)
		for subinstance in get_course_subinstances(course):
			result = self.do_import(subinstance, filer, writeout) or result
		return result
