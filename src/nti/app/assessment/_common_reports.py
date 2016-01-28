#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import csv
from io import BytesIO

import json
import isodate
from datetime import datetime

from zope import component

from zope.security.interfaces import IPrincipal

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistory

from nti.app.assessment.utils import replace_username

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseEnrollments

from nti.dataserver.interfaces import IUser

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.externalization import to_external_object

ITEMS = StandardExternalFields

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
		if principal is None:  # dupped enrollment
			continue

		user = IUser(record.Principal)
		username = user.username

		# filter user
		if usernames and username not in usernames:
			continue

		history = component.queryMultiAdapter((course, user),
											  IUsersCourseAssignmentHistory)
		if not history:
			continue

		for key, item in history.items():

			# filter assignment
			if assignment_id and assignment_id != key:
				continue

			submission = item.Submission
			createdTime = datetime.fromtimestamp(item.createdTime)
			for qs_part in submission.parts:

				# all question submissions
				for question in qs_part.questions:

					# filter question
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
	# return
	return stream, result
