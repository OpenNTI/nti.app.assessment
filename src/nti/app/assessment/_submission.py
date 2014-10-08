#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six
from cStringIO import StringIO

from zope import interface
from zope.proxy import ProxyBase
from zope.file.upload import nameFinder

from pyramid import httpexceptions as hexc

from ZODB.POSException import POSKeyError

from nti.assessment.interfaces import IQUploadedFile
from nti.assessment.interfaces import IInternalUploadedFileRef

from nti.externalization.externalization import to_external_ntiid_oid

from nti.utils.maps import CaseInsensitiveDict

class SourceProxy(ProxyBase):
	
	contentType = property(
					lambda s: s.__dict__.get('_v_content_type'),
					lambda s, v: s.__dict__.__setitem__('_v_content_type', v))
		
	filename  = property(
					lambda s: s.__dict__.get('_v_filename'),
					lambda s, v: s.__dict__.__setitem__('_v_filename', v))

	def __new__(cls, base, *args, **kwargs):
		return ProxyBase.__new__(cls, base)

	def __init__(self, base, filename=None, content_type=None):
		ProxyBase.__init__(self, base)
		self.filename = filename
		self.contentType = content_type
		
def get_source(request, *keys):
	values = CaseInsensitiveDict(request.POST)
	# check map
	source = None
	for key in keys:
		source = values.get(key)
		if source is not None:
			break
	if isinstance(source, six.string_types):
		source = StringIO(source)
		source.seek(0)
		source = SourceProxy(source, content_type='application/json')
	elif source is not None:
		filename = getattr(source, 'filename', None)
		content_type = getattr(source, 'type', None)
		source = source.file
		source.seek(0)
		source = SourceProxy(source, filename, content_type)
	return source

def read_multipart_sources(submission, request):
	sources = CaseInsensitiveDict(request.POST)
	for question_set in submission.parts:
		for question in question_set.questions:
			for part in question.parts:
				if not IQUploadedFile.providedBy(part) or part.size > 0:
					continue
				if not part.name:
					msg = 'No name was given to uploded file'
					raise hexc.HTTPUnprocessableEntity(msg)
				source = get_source(sources, part.name)
				if source is None:
					msg = 'Could not find data for file %s' % part.name
					raise hexc.HTTPUnprocessableEntity(msg)
				## copy data
				part.data = source.read()
				if not part.contentType and source.contentType:
					part.contentType = source.contentType
				if not part.filename and source.filename:
					part.filename = nameFinder(source)
	return submission

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
			# make sure we have a question set
			old_question_set = old_submission.get(question_set.questionSetId)
			if old_question_set is None:
				continue
			for question in question_set.questions:
				# make sure we have a question
				old_question = old_question_set.get(question.questionId)
				if old_question is None:
					continue
				for idx, part in enumerate(question.parts):
					# check there is a part
					try:
						old_part = old_question[idx]
					except IndexError:
						break
				
					# check if the uploaded file has been internalized empty 
					# this is tightly coupled w/ the way IQUploadedFile are updated.
					if IQUploadedFile.providedBy(old_part) and _is_internal(part):
						#TODO: Check against reference, delete old
						logger.info("Copy from previously uploaded file '%s(%s)'", 
									old_part.filename, to_external_ntiid_oid(old_part))
						part.data = old_part.data
						part.filename = old_part.filename
						part.contentType = old_part.contentType
						interface.noLongerProvides(part, IInternalUploadedFileRef)
		except POSKeyError:
			logger.exception("Failed to transfer data from savepoints")
			break
	return submission
