#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import lifecycleevent

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import make_evaluation_ntiid

from nti.app.assessment.interfaces import ICourseEvaluationEdition
from nti.app.assessment.interfaces import ICourseEvaluationEditions

from nti.app.base.abstract_views import get_all_sources

from nti.app.contentfile import validate_sources

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView

from nti.assessment.common import iface_of_assessment

from nti.dataserver import authorization as nauth

# def _get_filename(context, name):
# 	result = getattr(context, 'filename', None) or getattr(context, 'name', None) or name
# 	result = safe_filename(name_finder(result))
# 	return result
# 
# def _handle_multipart(context, user, model, sources):
# 	provided = ICourseDiscussion
# 	filer = get_course_filer(context, user)
# 	for name, source in sources.items():
# 		if name in provided:
# 			# remove existing
# 			location = getattr(discussion, name, None)
# 			if location:
# 				filer.remove(location)
# 			# save a in a new file
# 			key = _get_filename(source, name)
# 			location = filer.save(source, key, overwrite=False,
# 								  bucket=ASSETS_FOLDER, context=discussion)
# 			setattr(discussion, name, location)

@view_config(context=ICourseEvaluationEditions)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='POST',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationEditionsPostView(UGDPostView):

	content_predicate = ICourseEvaluationEdition.providedBy

	def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
		contentObject = self.doReadCreateUpdateContentObject(creator=creator,
															 search_owner=search_owner,
															 externalValue=externalValue)
		sources = get_all_sources(self.request)
		return contentObject, sources

	def _do_call(self):
		creator = self.remoteUser
		record, sources = self.readCreateUpdateContentObject(creator, search_owner=False)
		record.creator = creator.username
		record.updateLastMod()

		provided = iface_of_assessment(record.model)
		ntiid = make_evaluation_ntiid(provided, self.remoteUser)

		lifecycleevent.created(record)
		self.context[ntiid] = record
		
		# handle multi-part data
		if sources:  
			validate_sources(self.remoteUser, record.model, sources)
			# _handle_multipart(self.context, self.remoteUser, discussion, sources)

		self.request.response.status_int = 201
		return record

@view_config(context=ICourseEvaluationEdition)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='PUT',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationEditionPutView(UGDPutView):

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		result = UGDPutView.updateContentObject(self,
												contentObject,
												externalValue,
												set_id=set_id,
												notify=notify)

		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result, sources)
			# _handle_multipart(self.context, self.remoteUser, self.context, sources)
		return result
