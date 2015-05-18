#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
import sys
from io import BytesIO

import json
import isodate
from datetime import datetime

from zope import component
from zope import interface

from zope.file.upload import nameFinder

from zope.security.interfaces import IPrincipal

from zope.schema.interfaces import ConstraintNotSatisfied

from pyramid import httpexceptions as hexc

from ZODB.POSException import POSError

from nti.app.contentfile.view_mixins import get_source

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQFilePart
from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQUploadedFile
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IInternalUploadedFileRef

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver.interfaces import IUser

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.externalization import to_external_object
from nti.externalization.externalization import to_external_ntiid_oid

from ._utils import replace_username

from .interfaces import IUsersCourseAssignmentHistory

ITEMS = StandardExternalFields

def value_part(part):
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
				sub_part = value_part(sub_part)							
				if not IQUploadedFile.providedBy(sub_part):
					continue
	
				if not IQFilePart.providedBy(part):
					msg = 'Invalid submission. Expected a IQFilePart, instead it found %s' % part
					raise hexc.HTTPUnprocessableEntity(msg)
				
				max_size = part.max_file_size
				check_max_size(sub_part, max_size)
	return submission

def read_multipart_sources(submission, request):
	for question_set in submission.parts:
		for sub_question in question_set.questions:
			question = component.getUtility(IQuestion, sub_question.questionId)
			for part, sub_part in zip(question.parts, sub_question.parts):
				sub_part = value_part(sub_part)							
				if not IQUploadedFile.providedBy(sub_part):
					continue
	
				if not IQFilePart.providedBy(part):
					msg = 'Invalid submission. Expected a IQFilePart, instead it found %s' % part
					raise hexc.HTTPUnprocessableEntity(msg)
				
				max_size = part.max_file_size
				if sub_part.size > 0:
					check_max_size(sub_part, max_size)
				
				if not sub_part.name:
					msg = 'No name was given to uploded file'
					raise hexc.HTTPUnprocessableEntity(msg)
				source = get_source(request, sub_part.name)
				if source is None:
					msg = 'Could not find data for file %s' % sub_part.name
					raise hexc.HTTPUnprocessableEntity(msg)
				
				## copy data
				sub_part.data = source.read()
				check_max_size(sub_part, max_size)
				if not sub_part.contentType and source.contentType:
					sub_part.contentType = source.contentType
				if not sub_part.filename and source.filename:
					sub_part.filename = nameFinder(source)
	return submission

def _set_parent_(child, parent):
	if hasattr(child, '__parent__') and child.__parent__ is None:
		child.__parent__ = parent
			
def set_submission_lineage(submission):
	## The constituent parts of these things need parents as well.
	## XXX It would be nice if externalization took care of this,
	## but that would be a bigger change
	for submission_set in submission.parts:
		# submission_part e.g. assessed question set
		_set_parent_(submission_set, submission)
		for submitted_question in submission_set.questions:
			_set_parent_(submitted_question, submission_set)
			for submitted_question_part in submitted_question.parts:
				_set_parent_(submitted_question_part, submitted_question)
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

def transfer_upload_ownership(submission, old_submission, force=False):
	"""
	Search for previously uploaded files and make the part of the 
	new submission if nothing has changed.
	"""
	
	def _is_internal(source):
		if not IQUploadedFile.providedBy(source):
			return False
		if force:
			return True
		else:
			return 	IInternalUploadedFileRef.providedBy(source) or \
					not source.filename and source.size == 0
				
	# extra check
	if old_submission is None or submission is None:
		return submission
	
	for question_set in submission.parts:
		try:
			## make sure we have a question set
			old_question_set = old_submission.get(question_set.questionSetId)
			if old_question_set is None:
				continue
			for question in question_set.questions:
				## make sure we have a question
				old_question = old_question_set.get(question.questionId)
				if old_question is None:
					continue
				for idx, part in enumerate(question.parts):
					part = value_part(part)
					## check there is a part
					try:
						old_part = old_question[idx]
						old_part = value_part(old_part)
					except IndexError:
						break
					## check if the uploaded file has been internalized empty 
					## this is tightly coupled w/ the way IQUploadedFile are updated.
					if IQUploadedFile.providedBy(old_part) and _is_internal(part):
						logger.info("Copy from previously uploaded file '%s(%s)'", 
									old_part.filename, to_external_ntiid_oid(old_part))
						part.data = old_part.data
						part.filename = old_part.filename
						part.contentType = old_part.contentType
						interface.noLongerProvides(part, IInternalUploadedFileRef)
		except POSError:
			logger.exception("Failed to transfer data from savepoints")
			break
	return submission

def _tx_string(s):
	if s and isinstance(s, unicode):
		s = s.encode('utf-8')
	return s

def course_submission_report(context, usernames=(), assignment=None,
							 question=None, stream=None):
	
	question_id = question.ntiid \
				  if IQuestion.providedBy(question) else question
					
	assignment_id = assignment.ntiid \
					if IQAssignment.providedBy(assignment) else assignment
					
	stream = BytesIO() if stream is None else stream
	writer = csv.writer(stream)
	header = ['createdTime', 'username', 'assignment', 'question', 'part', 'submission']
	writer.writerow(header)
		
	result = LocatedExternalDict()
	items = result[ITEMS] = []
	course = ICourseInstance(context)
	course_enrollments = ICourseEnrollments(course)
	for record in course_enrollments.iter_enrollments():
		principal = IPrincipal(record.Principal, None)
		if principal is None: # dupped enrollment
			continue
		
		user = IUser(record.Principal)
		username = user.username
		
		## filter user 
		if usernames and username not in usernames:
			continue
		
		history = component.queryMultiAdapter( (course, user),
											  IUsersCourseAssignmentHistory )
		if not history:
			continue
		
		for key, item in history.items():
			## filter assignment 
			if assignment_id and assignment_id != key:
				continue

			submission = item.Submission
			createdTime = datetime.fromtimestamp(item.createdTime)
			for qs_part in submission.parts:
				## all question submissions
				for question in qs_part.questions:
					## filter question 
					if question_id and question.questionId != question_id:
						continue
					
					qid = question.questionId
					for idx, sub_part in enumerate(question.parts):
						ext = json.dumps(to_external_object(sub_part))
						row_data = [isodate.datetime_isoformat(createdTime),
									replace_username(username), key, qid, idx, ext]
						writer.writerow([_tx_string(x) for x in row_data])
						items.append({'part':idx,
									  'question':qid,
									  'assignment':key,
									  'submission':ext,
									  'username':username,
									  'created':createdTime})
	## return
	return stream, result
