#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment._assessment import move_user_assignment_from_course_to_course

from nti.app.assessment.views import parse_catalog_entry

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.internalization import read_body_as_external_object
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.views import CourseAdminPathAdapter

from nti.common.maps import CaseInsensitiveDict

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserverFolder

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   name='MoveUserAssignments')
class MoveUserAssignmentsView(AbstractAuthenticatedView,
							  ModeledContentUploadRequestUtilsMixin):

	def readInput(self, value=None):
		if self.request.body:
			values = read_body_as_external_object(self.request)
		else:
			values = self.request.params
		result = CaseInsensitiveDict(values)
		return result

	def __call__(self):
		values = self.readInput()
		source = parse_catalog_entry(values, names=("source", "origin"))
		target = parse_catalog_entry(values, names=("target", "dest"))
		if source is None:
			raise hexc.HTTPUnprocessableEntity("Invalid source NTIID")
		if target is None:
			raise hexc.HTTPUnprocessableEntity("Invalid target NTIID")
		if source == target:
			raise hexc.HTTPUnprocessableEntity("Source and Target courses are the same")

		source = ICourseInstance(source)
		target = ICourseInstance(target)

		usernames = values.get('usernames') or values.get('username')
		if usernames:
			usernames = usernames.split(',')
		else:
			usernames = tuple(ICourseEnrollments(source).iter_principals())

		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for username in usernames:
			user = User.get_user(username)
			if user is None or not IUser.providedBy(user):
				logger.info("User %s does not exists", username)
				continue
			moved = move_user_assignment_from_course_to_course(user, source, target)
			items[username] = sorted(moved)
		result[ITEM_COUNT] = result[TOTAL] = len(items)
		return result
