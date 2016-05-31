#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import zope.i18nmessageid
MessageFactory = zope.i18nmessageid.MessageFactory(__name__)

from zope import component

from zope.catalog.interfaces import ICatalog

from nti.app.assessment.index import EVALUATION_CATALOG_NAME
from nti.app.assessment.index import SUBMISSION_CATALOG_NAME

from nti.dataserver.interfaces import IMetadataCatalog

#: A view name to submit an assignment without persisting.
ASSESSMENT_PRACTICE_SUBMISSION = 'PracticeSubmission'

#: A view name to move questions between assessments.
VIEW_ASSESSMENT_MOVE = 'AssessmentMove'

#: The ordered-contents (insert) view for QuestionSets
VIEW_QUESTION_SET_CONTENTS = 'ordered-contents'

#: A view to mark the assessment object as randomized.
VIEW_RANDOMIZE = 'Randomize'

#: A view to mark the assessment object as unrandomized.
VIEW_UNRANDOMIZE = 'Unrandomize'

#: A view to mark the assessment object as containing randomized parts.
VIEW_RANDOMIZE_PARTS = 'RandomizeParts'

#: A view to mark the assessment object as not containing randomized parts.
VIEW_UNRANDOMIZE_PARTS = 'UnrandomizeParts'

def get_submission_catalog():
	return component.queryUtility(IMetadataCatalog, name=SUBMISSION_CATALOG_NAME)

def get_evaluation_catalog():
	return component.queryUtility(ICatalog, name=EVALUATION_CATALOG_NAME)
