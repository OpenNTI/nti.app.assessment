#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import six

from zope import component

from pyramid.view import view_config
from pyramid.view import view_defaults
from pyramid import httpexceptions as hexc

from nti.app.base.abstract_views import AbstractAuthenticatedView
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.contenttypes.courses.interfaces import ICourseCatalog
from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser
from nti.dataserver import authorization as nauth
from nti.dataserver.interfaces import IDataserverFolder

from nti.externalization.interfaces import LocatedExternalDict

from nti.utils.maps import CaseInsensitiveDict

from .history import move_assignment_histories
from .interfaces import ICourseAssessmentItemCatalog

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_MODERATE,
			   request_method='GET',
			   name='AllTasksOutline') # See decorators
class AllTasksOutlineView(AbstractAuthenticatedView):

	def __call__(self):
		instance = ICourseInstance(self.request.context)
		catalog = ICourseAssessmentItemCatalog(instance)

		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		for item in catalog.iter_assessment_items():
			unit = item.__parent__
			result.setdefault(unit.ntiid, []).append(item)
		return result

@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   context=IDataserverFolder,
			   permission=nauth.ACT_MODERATE,
			   name='MoveUserCourseAssignmentHistories')
class MoveUserCourseAssignmentHistoriesView(AbstractAuthenticatedView,
							  				ModeledContentUploadRequestUtilsMixin):

	def readInput(self):
		values = super(MoveUserCourseAssignmentHistoriesView, self).readInput()
		result = CaseInsensitiveDict(values)
		return result

	def __call__(self):
		values = self.readInput()
		username = values.get('username') or values.get('user')
		if not username:
			raise hexc.HTTPUnprocessableEntity(detail='No username')

		user = User.get_user(username)
		if not user or not IUser.providedBy(user):
			raise hexc.HTTPNotFound(detail='User not found')

		entries = {}
		for name in ('target', 'source'):
			ntiid = values.get(name)
			if not ntiid:
				raise hexc.HTTPUnprocessableEntity('No %s course identifier' % name)
		
			try:
				catalog = component.getUtility(ICourseCatalog)
				entry = catalog.getCatalogEntry(ntiid)
				entries[name] = entry
			except LookupError:
				raise hexc.HTTPNotFound('Catalog not found')
			except KeyError:
				raise hexc.HTTPNotFound('Course not found')
			
		assignments = values.get('assignments') or values.get('assignmentsIds')
		if isinstance(assignments, six.string_types):
			assignments = assignments.split()

		moved = move_assignment_histories(user,
										  ICourseInstance(entries['source']),
										  ICourseInstance(entries['target']),
										  assignments=assignments)
		result = LocatedExternalDict()
		result['Items'] = moved
		return result
