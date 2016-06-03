#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
from urlparse import urlparse

from html5lib import HTMLParser
from html5lib import treebuilders

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from persistent.list import PersistentList

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common import has_savepoints
from nti.app.assessment.common import has_submissions
from nti.app.assessment.common import get_resource_site_name
from nti.app.assessment.common import get_available_assignments_for_evaluation_object

from nti.app.base.abstract_views import get_safe_source_filename

from nti.app.externalization.error import raise_json_error

from nti.app.products.courseware import ASSETS_FOLDER

from nti.app.products.courseware.resources.interfaces import ICourseContentResource

from nti.app.products.courseware.resources.utils import get_course_filer
from nti.app.products.courseware.resources.utils import is_internal_file_link
from nti.app.products.courseware.resources.utils import get_file_from_external_link

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQHint
from nti.assessment.interfaces import IQPart
from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignmentPart
from nti.assessment.interfaces import IQEvaluationItemContainer

from nti.contentfile.interfaces import IContentBaseFile

from nti.contentfragments.html import _html5lib_tostring

from nti.contentfragments.interfaces import IHTMLContentFragment

from nti.contenttypes.courses.interfaces import NTI_COURSE_FILE_SCHEME

from nti.site.hostpolicy import get_host_site

from nti.site.utils import registerUtility

def indexed_iter():
	return PersistentList()

def associate(model, source):
	if IContentBaseFile.providedBy(source):
		source.add_association(model)

def get_html_content_fields(context):
	result = []
	if IQHint.providedBy(context):
		result.append((context, 'value'))
	elif IQPart.providedBy(context):
		result.append((context, 'content'))
		result.append((context, 'explanation'))
		for hint in context.hints or ():
			result.extend(get_html_content_fields(hint))
	elif 	IQAssignment.providedBy(context) \
		or	IQuestion.providedBy(context) \
		or	IQPoll.providedBy(context):
		result.append((context, 'content'))
		for part in context.parts or ():
			result.extend(get_html_content_fields(part))
	elif IQuestionSet.providedBy(context) or IQSurvey.providedBy(context):
		for question in context.questions or ():
			result.extend(get_html_content_fields(question))
	elif IQAssignmentPart.providedBy(context):
		result.append((context, 'content'))
		result.extend(get_html_content_fields(context.question_set))
	elif IQAssignment.providedBy(context):
		result.append((context, 'content'))
		for parts in context.parts or ():
			result.extend(get_html_content_fields(parts))
	return tuple(result)

def import_evaluation_content(model, context=None, user=None, sources=None,
							  source_filer=None, target_filer=None):
	if source_filer is None:
		source_filer = get_course_filer(context, user)
	if target_filer is None:
		target_filer = source_filer
	sources = sources if sources is not None else {}
	for obj, name in get_html_content_fields(model):
		value = getattr(obj, name, None)
		if value and source_filer != None:
			modified = False
			value = IHTMLContentFragment(value)
			parser = HTMLParser(tree=treebuilders.getTreeBuilder("lxml"),
								namespaceHTMLElements=False)
			doc = parser.parse(value)
			for e in doc.iter():
				attrib = e.attrib
				href = attrib.get('href')
				if not href:
					continue
				elif is_internal_file_link(href):
					source = get_file_from_external_link(href)
					associate(model, source)
				elif href.startswith(NTI_COURSE_FILE_SCHEME):
					save_in_filer = True
					path = urlparse(href).path
					path, name = os.path.split(path)
					source = sources.get(name)
					if source is None:
						source = source_filer.get(name, path)
						if source is not None:
							associate(model, source)
							location = source_filer.get_external_link(source)
							save_in_filer = target_filer is not source_filer
						else:
							logger.error("Missing source %s", href)
							continue
					if source is not None and save_in_filer:
						path = path or ASSETS_FOLDER
						key = get_safe_source_filename(source, name)
						location = target_filer.save(key, source, overwrite=False,
											  		 bucket=path, context=model)
					# change href
					attrib['href'] = location
					modified = True

			if modified:
				value = _html5lib_tostring(doc, sanitize=False)
				setattr(obj, name, value)
	return model

def export_evaluation_content(model, source_filer, target_filer):
	for obj, name in get_html_content_fields(model):
		value = getattr(obj, name, None)
		if not value:
			continue
		modified = False
		value = IHTMLContentFragment(value)
		parser = HTMLParser(tree=treebuilders.getTreeBuilder("lxml"),
							namespaceHTMLElements=False)
		doc = parser.parse(value)
		for e in doc.iter():
			attrib = e.attrib
			href = attrib.get('href')
			if not href:
				continue
			elif is_internal_file_link(href):
				resource = get_file_from_external_link(href)
				contentType = resource.contentType
				ICourseContentResource
				if ICourseContentResource.providedBy(resource) and hasattr(resource, 'path'):
					path = resource.path
					path = os.path.split(path)[0]  # remove resource name
					path = path[1:] if path.startswith('/') else path
				else:
					path = ASSETS_FOLDER
				# save resource
				target_filer.save(resource.name,
								  resource,
								  bucket=path,
								  context=obj,
								  overwrite=True,
								  contentType=contentType)
				# get course file scheme
				internal = NTI_COURSE_FILE_SCHEME + path + "/" + resource.name
				attrib['href'] = internal
				modified = True

		if modified:
			value = _html5lib_tostring(doc, sanitize=False)
			setattr(obj, name, value)
	return model

def register_context(context, site_name=None):
	ntiid = context.ntiid
	provided = iface_of_assessment(context)
	site_name = get_resource_site_name(context) if not site_name else site_name
	registry = get_host_site(site_name).getSiteManager()
	if registry.queryUtility(provided, name=ntiid) is None:
		registerUtility(registry, context, provided, name=ntiid)
	# process 'children'
	if IQEvaluationItemContainer.providedBy(context):
		for item in context.Items or ():
			register_context(item, site_name)
	elif IQAssignment.providedBy(context):
		for item in context.iter_question_sets():
			register_context(item, site_name)

def validate_submissions(theObject, course, request=None):
	if has_submissions(theObject, course):
		request = request or get_current_request()
		raise_json_error(request,
						 hexc.HTTPUnprocessableEntity,
						 {
							u'message': _("Object has submissions."),
							u'code': 'ObjectHasSubmissions',
						 },
						 None)

def validate_savepoints(theObject, course, request=None):
	if has_savepoints(theObject, course):
		request = request or get_current_request()
		raise_json_error(request,
						 hexc.HTTPUnprocessableEntity,
						 {
							u'message': _("Object has savepoints"),
							u'code': 'ObjectHasSavepoints',
						 },
						 None)

def validate_assignment(theObject, request=None):
	assignments = get_available_assignments_for_evaluation_object(theObject)
	if assignments:
		request = request or get_current_request()
		raise_json_error(request,
						 hexc.HTTPUnprocessableEntity,
						 {
							u'message': _("Object is in available assignments."),
							u'code': 'ObjectInAvailableAssignments',
						 },
						 None)

def validate_structural_edits(theObject, course, request=None):
	"""
	Validate that we can structurally edit the given evaluation object.
	"""
	validate_savepoints(theObject, course, request)
	validate_submissions(theObject, course, request)
	validate_assignment(theObject, request)
