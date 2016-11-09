#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.assessment.interfaces import IPlaceholderAssignmentSubmission

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.externalization.interfaces import IExternalMappingDecorator

from nti.externalization.singleton import SingletonDecorator

@interface.implementer(IExternalMappingDecorator)
@component.adapter(IUsersCourseAssignmentHistoryItem)
class _SyntheticSubmissionDecorator(object):
	"""
	Decorate placeholder submissions as synthetic submissions.
	"""

	__metaclass__ = SingletonDecorator

	def decorateExternalMapping(self, item, result_map):
		submission = item.Submission
		is_synth = IPlaceholderAssignmentSubmission.providedBy( submission )
		result_map['SyntheticSubmission'] = is_synth
