#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import lifecycleevent

from persistent.list import PersistentList

from nti.assessment.assignment import QAssignmentSubmissionPendingAssessment

from nti.assessment.interfaces import IQResponse
from nti.assessment.interfaces import IQAssessedQuestionSet

from nti.base.interfaces import INamedFile

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.traversal.traversal import find_interface


def set_parent(child, parent):
    if hasattr(child, '__parent__') and child.__parent__ is None:
        child.__parent__ = parent


def get_part_value(part):
    if IQResponse.providedBy(part):
        part = part.value
    return part


def set_part_value_lineage(part):
    part_value = get_part_value(part)
    if part_value is not part and INamedFile.providedBy(part_value):
        set_parent(part_value, part)


def set_assessed_lineage(assessed):
    # The constituent parts of these things need parents as well.
    # It would be nice if externalization took care of this,
    # but that would be a bigger change
    creator = getattr(assessed, 'creator', None)
    for assessed_set in assessed.parts or ():
        # submission_part e.g. assessed question set
        set_parent(assessed_set, assessed)
        assessed_set.creator = creator
        for assessed_question in assessed_set.questions or ():
            assessed_question.creator = creator
            set_parent(assessed_question, assessed_set)
            for assessed_question_part in assessed_question.parts or ():
                set_parent(assessed_question_part, assessed_question)
                set_part_value_lineage(assessed_question_part)
    return assessed


def assess_assignment_submission(unused_context, assignment, submission):
    # Ok, now for each part that can be auto graded, do so, leaving all the others
    # as-they-are
    new_parts = PersistentList()
    for submission_part in submission.parts:
        assignment_part, = [p for p in assignment.parts
                            if p.question_set.ntiid == submission_part.questionSetId]
        # Only assess if the part is set to auto_grade.
        if assignment_part.auto_grade:
            __traceback_info__ = submission_part
            submission_part = IQAssessedQuestionSet(submission_part)
        new_parts.append(submission_part)
    # create a pending assessment object
    pending_assessment = QAssignmentSubmissionPendingAssessment(assignmentId=submission.assignmentId,
                                                                parts=new_parts)
    pending_assessment.containerId = submission.assignmentId
    return pending_assessment


def reassess_assignment_history_item(item):
    """
    Update our submission by re-assessing the changed question.
    """
    submission = item.Submission
    old_pending_assessment = item.pendingAssessment
    if submission is None or old_pending_assessment is None:
        return

    # mark old pending assessment as removed
    lifecycleevent.removed(old_pending_assessment)
    old_pending_assessment.__parent__ = None  # ground

    assignment = item.Assignment
    course = find_interface(item, ICourseInstance, strict=False)
    new_pending_assessment = assess_assignment_submission(course,
                                                          assignment,
                                                          submission)
    old_duration = old_pending_assessment.CreatorRecordedEffortDuration
    new_pending_assessment.CreatorRecordedEffortDuration = old_duration

    item.pendingAssessment = new_pending_assessment
    new_pending_assessment.__parent__ = item
    set_assessed_lineage(new_pending_assessment)
    lifecycleevent.created(new_pending_assessment)

    # dispatch to sublocations
    lifecycleevent.modified(item)