#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NTIID support for assessments in the application.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface
from zope import component

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment

from nti.ntiids.interfaces import INTIIDResolver

@interface.implementer(INTIIDResolver)
class _AssessmentResolver(object):
	"""
	A resolver for the :const:`nti.assessment.interfaces.NTIID_TYPE`
	value. This one single type of ntiid is used for questions,
	question sets, and assignments. We expect to be able to
	resolve these using the current component registry.
	"""

	def resolve(self, key):
		for iface in (IQuestion, IQuestionSet, IQAssignment, IQPoll, IQSurvey):
			result = component.queryUtility(iface, name=key)
			if result is not None:
				break
		return result
