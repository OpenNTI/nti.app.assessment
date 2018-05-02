#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import zope.i18nmessageid
MessageFactory = zope.i18nmessageid.MessageFactory(__name__)

#: A view name to submit an assignment without persisting.
ASSESSMENT_PRACTICE_SUBMISSION = 'PracticeSubmission'

#: A view name to move questions between assessments.
VIEW_ASSESSMENT_MOVE = 'AssessmentMove'

#: The ordered-contents (insert) view for QuestionSets
VIEW_QUESTION_SET_CONTENTS = 'ordered-contents'

#: The self-assessments view for QuestionSets
VIEW_QUESTION_SET_SELF_ASSESSMENTS = 'self-assessments'

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

#: A marker rel to signify that this evaluation object can be deleted.
VIEW_DELETE = 'Delete'

#: A marker rel to signify that this evaluation object allows part option insertion.
VIEW_INSERT_PART_OPTION = 'InsertPartOption'

#: A marker rel to signify that this evaluation object allows part option removal.
VIEW_REMOVE_PART_OPTION = 'RemovePartOption'

#: A marker rel to signify that this evaluation object allows part option moves.
VIEW_MOVE_PART_OPTION = 'MovePartOption'

#: A marker rel to signify that this assignment can change is-non-public state.
VIEW_IS_NON_PUBLIC = 'IsNonPublic'

#: A view to copy an evaluation
VIEW_COPY_EVALUATION = 'Copy'

#: A view to reset an evaluation
VIEW_RESET_EVALUATION = 'Reset'

#: A view to reset an evaluation for user
VIEW_USER_RESET_EVALUATION = 'UserReset'

#: A view to reasses an evaluation
VIEW_REGRADE_EVALUATION = 'Regrade'

#: A view to unlock assignment policies
VIEW_UNLOCK_POLICIES = 'UnlockPolicies'

#: A view to fetch all question containers.
VIEW_QUESTION_CONTAINERS = 'Assessments'

#: A view to fetch the topic associated with an IQDiscussionAssignment
VIEW_RESOLVE_TOPIC = 'ResolveTopic'

#: A view to download the submitted assignment file-parts of a course.
VIEW_COURSE_ASSIGNMENT_BULK_FILE_PART_DOWNLOAD = 'CourseAssignmentBulkFilePartDownload'

from nti.app.assessment.index import EVALUATION_CATALOG_NAME
from nti.app.assessment.index import SUBMISSION_CATALOG_NAME

from nti.app.assessment.index import get_submission_catalog
from nti.app.assessment.index import get_evaluation_catalog
