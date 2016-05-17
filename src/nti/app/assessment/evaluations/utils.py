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

from nti.app.base.abstract_views import get_safe_source_filename

from nti.app.products.courseware import ASSETS_FOLDER

from nti.app.products.courseware.resources.utils import get_course_filer
from nti.app.products.courseware.resources.utils import is_internal_file_link
from nti.app.products.courseware.resources.utils import get_file_from_external_link

from nti.assessment.interfaces import IQHint
from nti.assessment.interfaces import IQPart
from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignmentPart

from nti.contentfile.interfaces import IContentBaseFile

from nti.contentfragments.html import _html5lib_tostring

from nti.contentfragments.interfaces import IHTMLContentFragment

from nti.contenttypes.courses.interfaces import NTI_COURSE_FILE_SCHEME

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

def import_evaluation_content(context, user, model, sources=None):
	filer = get_course_filer(context, user)
	sources = sources if sources is not None else {}
	for obj, name in get_html_content_fields(model):
		value = getattr(obj, name, None)
		if value and filer != None:
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
					# save resource in filer
					path = urlparse(href).path
					path, name = os.path.split(path)
					source = sources.get(name)
					if source is None:
						source = filer.get(name, path)
						if source is not None:
							associate(model, source)
							location = filer.get_external_link(source)
						else:
							logger.error("Missing multipart-source %s", href)
							continue
					else:
						path = path or ASSETS_FOLDER
						key = get_safe_source_filename(source, name)
						location = filer.save(key, source, overwrite=False,
											  bucket=path, context=model)
					# change href
					attrib['href'] = location
					modified = True

			if modified:
				value = _html5lib_tostring(doc, sanitize=False)
				setattr(obj, name, value)
	return model
