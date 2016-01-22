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

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment._assessment import move_user_assignment_from_course_to_course

from nti.app.assessment._common_reports import course_submission_report

from nti.app.assessment.common import get_course_assignments

from nti.app.assessment.views import parse_catalog_entry

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.externalization.internalization import read_body_as_external_object
from nti.app.externalization.view_mixins import ModeledContentUploadRequestUtilsMixin

from nti.app.products.courseware.views import CourseAdminPathAdapter

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.common.maps import CaseInsensitiveDict

from nti.common.string import TRUE_VALUES

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver import authorization as nauth

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import IDataserverFolder

from nti.dataserver.users import User

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_config(name='CourseSubmissionReport')
@view_defaults(route_name='objects.generic.traversal',
				renderer='rest',
				permission=nauth.ACT_NTI_ADMIN,
				request_method='GET')
class CourseSubmissionReportView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")

		usernames = params.get('usernames') or params.get('username')
		if isinstance(usernames, six.string_types):
			usernames = usernames.split(',')
		usernames = {x.lower() for x in usernames or ()}

		assignment = params.get('assignmentId') or params.get('assignment')
		if assignment and component.queryUtility(IQAssignment, name=assignment) is None:
			raise hexc.HTTPUnprocessableEntity("Invalid assignment")

		question = params.get('questionId') or params.get('question')
		if question and component.queryUtility(IQuestion, name=question) is None:
			raise hexc.HTTPUnprocessableEntity("Invalid question")

		response = self.request.response
		response.content_encoding = str('identity')
		response.content_type = str('text/csv; charset=UTF-8')
		response.content_disposition = str('attachment; filename="report.csv"')

		stream, _ = course_submission_report(context=context,
							 	 		  	 question=question,
							 	 		 	 usernames=usernames,
								 		 	 assignment=assignment)
		stream.flush()
		stream.seek(0)
		response.body_file = stream
		return response

@view_config(context=IDataserverFolder)
@view_config(context=CourseAdminPathAdapter)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_NTI_ADMIN,
			   request_method='GET',
			   name='CourseAssignments')
class CourseAssignmentsView(AbstractAuthenticatedView):

	def __call__(self):
		params = CaseInsensitiveDict(self.request.params)
		context = parse_catalog_entry(params)
		if context is None:
			raise hexc.HTTPUnprocessableEntity("Invalid course NTIID")
		course = ICourseInstance(context)

		do_filtering = params.get('filter') or TRUE_VALUES[0]
		do_filtering = do_filtering.lower() in TRUE_VALUES

		result = LocatedExternalDict()
		items = result[ITEMS] = {}
		for assignment in get_course_assignments(course=course,
												 do_filtering=do_filtering):
			items[assignment.ntiid] = assignment
		result['ItemCount'] = result['Total'] = len(items)
		return result

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
		result['ItemCount'] = result['Total'] = len(items)
		return result
