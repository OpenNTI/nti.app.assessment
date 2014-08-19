#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generations for managing assesments.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import zope.intid

from zope import component

from ZODB.POSException import POSKeyError

from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssessedQuestion

def all_assessed_questions(intids=None):
	obj = None
	intids = intids or component.getUtility(zope.intid.IIntIds)
	for uid in intids:
		try:
			obj = intids.getObject(uid)
			if IQAssessedQuestion.providedBy(obj):
				yield uid, obj
		except (POSKeyError, TypeError) as e:
			logger.error("Ignoring %s(%s); %s", type(obj), uid, e)

def _all_randomized_multiplechoice_multiple_answer_parts(intids=None):
	
	for assessed in all_assessed_questions(intids):
		questionId = assessed.questionId
		question = component.queryUtility(IQuestion, questionId)
		if question is None:
			continue
