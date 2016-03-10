#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import sys

from zope import component
from zope import interface

from zope.schema.interfaces import ConstraintNotSatisfied

from ZODB.POSException import POSError

from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import get_source

from nti.app.contentfile import transfer_data

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQFilePart
from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IInternalUploadedFileRef

from nti.namedfile.interfaces import INamedFile

def _set_parent_(child, parent):
	if hasattr(child, '__parent__') and child.__parent__ is None:
		child.__parent__ = parent

def get_part_value(part):
	if IQResponse.providedBy(part):
		part = part.value
	return part

def check_max_size(part, max_file_size=None):
	size = part.size
	max_file_size = max_file_size or sys.maxint
	if size > max_file_size:
		raise ConstraintNotSatisfied(size, 'max_file_size')
	return part

def check_upload_files(submission):
	for question_set in submission.parts:
		for sub_question in question_set.questions:
			question = component.getUtility(IQuestion, sub_question.questionId)
			for part, sub_part in zip(question.parts, sub_question.parts):
				part_value = get_part_value(sub_part)
				if not INamedFile.providedBy(part_value):
					continue

				if not IQFilePart.providedBy(part):
					msg = 'Invalid submission. Expected a IQFilePart, instead it found %s' % part
					raise hexc.HTTPUnprocessableEntity(msg)

				max_size = part.max_file_size
				check_max_size(part_value, max_size)
	return submission

def read_multipart_sources(submission, request):
	for question_set in submission.parts:
		for sub_question in question_set.questions:
			question = component.getUtility(IQuestion, sub_question.questionId)
			for part, sub_part in zip(question.parts, sub_question.parts):
				part_value = get_part_value(sub_part)
				if not INamedFile.providedBy(part_value):
					continue

				if not IQFilePart.providedBy(part):
					msg = 'Invalid submission. Expected a IQFilePart, instead it found %s' % part
					raise hexc.HTTPUnprocessableEntity(msg)

				max_size = part.max_file_size
				if part_value.size > 0:
					check_max_size(part_value, max_size)

				if not part_value.name:
					msg = 'No name was given to uploded file'
					raise hexc.HTTPUnprocessableEntity(msg)

				source = get_source(request, part_value.name)
				if source is None:
					msg = 'Could not find data for file %s' % part_value.name
					raise hexc.HTTPUnprocessableEntity(msg)

				# copy data
				transfer_data(source, part_value)
	return submission

def _set_part_value_lineage(part):
	part_value = get_part_value(part)
	if part_value is not part and INamedFile.providedBy(part_value):
		_set_parent_(part_value, part)
				
def set_submission_lineage(submission):
	# The constituent parts of these things need parents as well.
	# It would be nice if externalization took care of this,
	# but that would be a bigger change
	for submission_set in submission.parts:
		# submission_part e.g. assessed question set
		_set_parent_(submission_set, submission)
		for submitted_question in submission_set.questions:
			_set_parent_(submitted_question, submission_set)
			for submitted_question_part in submitted_question.parts:
				_set_parent_(submitted_question_part, submitted_question)
				_set_part_value_lineage(submitted_question_part)
	return submission

def set_poll_submission_lineage(submission):
	for submitted_question_part in submission.parts:
		_set_parent_(submitted_question_part, submission)
	return submission

def set_survey_submission_lineage(submission):
	for submitted_question in submission.questions:
		_set_parent_(submitted_question, submission)
		set_poll_submission_lineage(submitted_question)
	return submission

def set_inquiry_submission_lineage(submission):
	if IQPollSubmission.providedBy(submission):
		set_poll_submission_lineage(submission)
	elif IQSurveySubmission.providedBy(submission):
		set_survey_submission_lineage(submission)
	return submission

def transfer_submission_file_data(source, target,  force=False):
	"""
	Search for previously uploaded files and make them part of the
	new submission if nothing has changed.
	
	:param sorce Source submission
	:param target Target submission
	"""

	def _is_internal(source):
		if not INamedFile.providedBy(source):
			return False
		if force:
			return True
		else:
			result =	IInternalUploadedFileRef.providedBy(source) \
					or	(not source.filename and source.size == 0)
			return result

	# extra check
	if source is None or target is None:
		return target

	for question_set in target.parts:
		try:
			# make sure we have a question set
			old_question_set = source.get(question_set.questionSetId)
			if old_question_set is None:
				continue
			for question in question_set.questions:
				# make sure we have a question
				old_question = old_question_set.get(question.questionId)
				if old_question is None:
					continue
				for idx, part in enumerate(question.parts):
					part_value = get_part_value(part)
					# check there is a part
					try:
						old_part = old_question[idx]
						old_part_value = get_part_value(old_part)
					except IndexError:
						break
					# check if the uploaded file has been internalized empty
					# this is tightly coupled w/ the way IQUploadedFile are updated.
					if INamedFile.providedBy(old_part_value) and _is_internal(part_value):
						part_value.data = old_part_value.data
						part_value.filename = old_part_value.filename
						part_value.contentType = old_part_value.contentType
						interface.noLongerProvides(part_value, IInternalUploadedFileRef)
		except POSError:
			logger.exception("Failed to transfer data from savepoints")
			break
	return target
