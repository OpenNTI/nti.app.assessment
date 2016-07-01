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

from nti.zope_catalog.interfaces import IMetadataCatalog

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
VIEW_RANDOMIZE_PARTS = 'RandomizePartsType'

#: A view to mark the assessment object as not containing randomized parts.
VIEW_UNRANDOMIZE_PARTS = 'UnrandomizePartsType'

#: A marker rel to signify that this evaluation object allows part insertion.
VIEW_INSERT_PART = 'InsertPart'

#: A marker rel to signify that this evaluation object allows part removal.
VIEW_REMOVE_PART = 'RemovePart'

#: A marker rel to signify that this evaluation object allows part moves.
VIEW_MOVE_PART = 'MovePart'

#: A marker rel to signify that this evaluation object allows part option insertion.
VIEW_INSERT_PART_OPTION = 'InsertPartOption'

#: A marker rel to signify that this evaluation object allows part option removal.
VIEW_REMOVE_PART_OPTION = 'RemovePartOption'

#: A marker rel to signify that this evaluation object allows part option moves.
VIEW_MOVE_PART_OPTION = 'MovePartOption'

#: A view to copy an evaluation
VIEW_COPY_EVALUATION = 'Copy'

#: A view to reset an evaluation
VIEW_RESET_EVALUATION = 'Reset'

#: A view to reset an evaluation for user
VIEW_USER_RESET_EVALUATION = 'UserReset'

def get_submission_catalog():
	return component.queryUtility(IMetadataCatalog, name=SUBMISSION_CATALOG_NAME)

def get_evaluation_catalog():
	return component.queryUtility(ICatalog, name=EVALUATION_CATALOG_NAME)
