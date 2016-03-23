#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import copy

from zope import interface
from zope import lifecycleevent

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment.common import make_evaluation_ntiid

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.assessment.views import MessageFactory as _

from nti.app.assessment.views.view_mixins import AssessmentPutView

from nti.app.base.abstract_views import get_all_sources
from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.view_mixins import BatchingUtilsMixin

from nti.app.contentfile import validate_sources

from nti.appserver.ugd_edit_views import UGDPutView
from nti.appserver.ugd_edit_views import UGDPostView
from nti.appserver.ugd_edit_views import UGDDeleteView

from nti.assessment.common import iface_of_assessment

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQEditable
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation

from nti.common.maps import CaseInsensitiveDict

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.internalization import notifyModified

ITEMS = StandardExternalFields.ITEMS

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
# 			key = get_safe_source_filename(source, name)
# 			location = filer.save(source, key, overwrite=False,
# 								  bucket=ASSETS_FOLDER, context=discussion)
# 			setattr(discussion, name, location)

@view_config(context=ICourseEvaluations)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='GET',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationsGetView(AbstractAuthenticatedView, BatchingUtilsMixin):

	_DEFAULT_BATCH_SIZE = 50
	_DEFAULT_BATCH_START = 0

	def _get_mimeTypes(self):
		params = CaseInsensitiveDict(self.request.params)
		result = params.get('accept') or params.get('mimeType')
		if result:
			result = set(result.split(','))
		return result or ()

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context
		result.lastModified = self.context.lastModified
		mimeTypes = self._get_mimeTypes()
		items = result[ITEMS] = []
		if mimeTypes:
			items.extend(x for x in self.context.values() if x.mimeType in mimeTypes)
		else:
			items.extend(self.context.values())

		result['TotalItemCount'] = len(items)
		self._batch_items_iterable(result, items)
		result['ItemCount'] = len(result[ITEMS])
		return result

@view_config(context=ICourseEvaluations)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='POST',
			   permission=nauth.ACT_CONTENT_EDIT)
class CourseEvaluationsPostView(UGDPostView):

	content_predicate = IQEvaluation.providedBy

	def readCreateUpdateContentObject(self, creator, search_owner=False, externalValue=None):
		contentObject = self.doReadCreateUpdateContentObject(creator=creator,
															 search_owner=search_owner,
															 externalValue=externalValue)
		sources = get_all_sources(self.request)
		return contentObject, sources

	def _do_call(self):
		creator = self.remoteUser
		evaluation, sources = self.readCreateUpdateContentObject(creator, search_owner=False)
		evaluation.creator = creator.username
		interface.alsoProvides(evaluation, IQEditable)

		provided = iface_of_assessment(evaluation)
		ntiid = make_evaluation_ntiid(provided, self.remoteUser)

		lifecycleevent.created(evaluation)
		evaluation.ntiid = ntiid
		self.context[ntiid] = evaluation  # save

		# handle multi-part data
		if sources:
			validate_sources(self.remoteUser, evaluation, sources)
			# _handle_multipart(self.context, self.remoteUser, discussion, sources)

		self.request.response.status_int = 201
		return evaluation

@view_config(context=IQEvaluation)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   request_method='PUT',
			   permission=nauth.ACT_CONTENT_EDIT)
class EvaluationPutView(UGDPutView):

	def _check_object_constraints(self, obj):
		UGDPutView._check_object_constraints(self, obj)
		if not IQEditable.providedBy(obj):
			raise hexc.HTTPPreconditionFailed(_("Cannot change object definition."))

	def updateContentObject(self, contentObject, externalValue, set_id=False, notify=True):
		originalSource = copy.copy(externalValue)
		result = UGDPutView.updateContentObject(self,
												contentObject,
												externalValue,
												set_id=set_id,
												notify=False)

		sources = get_all_sources(self.request)
		if sources:
			validate_sources(self.remoteUser, result.model, sources)
			# _handle_multipart(self.context, self.remoteUser, self.context, sources)
		notifyModified(contentObject, originalSource)
		return result

@view_config(route_name='objects.generic.traversal',
			 context=IQPoll,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class PollPutView(AssessmentPutView):

	TO_AVAILABLE_MSG = _('Poll will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Poll will become unavailable. Please confirm.')

	def validate(self, contentObject, externalValue, courses=()):
		super(PollPutView, self).validate(contentObject, externalValue, courses)
		parts = externalValue.get('parts')
		if not IQEditable.providedBy(contentObject) and parts:
			raise hexc.HTTPForbidden(_("Cannot change the definition of a poll."))

@view_config(route_name='objects.generic.traversal',
			 context=IQSurvey,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class SurveyPutView(AssessmentPutView):

	TO_AVAILABLE_MSG = _('Survey will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Survey will become unavailable. Please confirm.')

	def validate(self, contentObject, externalValue, courses=()):
		super(SurveyPutView, self).validate(contentObject, externalValue, courses)
		questions = externalValue.get('questions')
		if not IQEditable.providedBy(contentObject) and questions:
			raise hexc.HTTPForbidden(_("Cannot change the definition of a survey."))

@view_config(route_name='objects.generic.traversal',
			 context=IQAssignment,
			 request_method='PUT',
			 permission=nauth.ACT_CONTENT_EDIT,
			 renderer='rest')
class AssignmentPutView(AssessmentPutView):

	TO_AVAILABLE_MSG = _('Assignment will become available. Please confirm.')
	TO_UNAVAILABLE_MSG = _('Assignment will become unavailable. Please confirm.')

	def validate(self, contentObject, externalValue, courses=()):
		super(AssignmentPutView, self).validate(contentObject, externalValue, courses)
		parts = externalValue.get('parts')
		if not IQEditable.providedBy(contentObject) and parts:
			raise hexc.HTTPForbidden(_("Cannot change the definition of an assignment."))

@view_config(route_name="objects.generic.traversal",
			 context=IQEvaluation,
			 renderer='rest',
			 permission=nauth.ACT_DELETE,
			 request_method='DELETE')
class EvaluationDeleteView(UGDDeleteView):

	def _do_delete_object(self, theObject):
		if not IQEditable.providedBy(theObject):
			raise hexc.HTTPForbidden(_("Cannot delete legacy object."))
		del theObject.__parent__[theObject.__name__]
		return theObject
