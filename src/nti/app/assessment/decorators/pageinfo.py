#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component
from zope import interface

from nti.app.assessment.common.evaluations import get_assessment_items_from_unit
from nti.app.assessment.common.evaluations import AssessmentItemProxy as AssignmentProxy

from nti.app.assessment.utils import check_assignment
from nti.app.assessment.utils import get_course_from_request

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator

from nti.app.contentlibrary.interfaces import IContentUnitInfo

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IRandomizedQuestionSet

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.courses.utils import is_enrolled
from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields
from nti.externalization.interfaces import IExternalMappingDecorator

from nti.ntiids.oids import to_external_ntiid_oid

TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT

logger = __import__('logging').getLogger(__name__)


@component.adapter(IContentUnitInfo)
@interface.implementer(IExternalMappingDecorator)
class _ContentUnitAssessmentItemDecorator(AbstractAuthenticatedRequestAwareDecorator):

    def _predicate(self, context, result_map):
        return (    AbstractAuthenticatedRequestAwareDecorator._predicate(self, context, result_map)
                and context.contentUnit is not None)

    def _get_course(self, contentUnit, user):
        result = get_course_from_request(self.request)
        if result is not None:
            # CS: make sure the user is either enrolled or is an instructor in the
            # course passed as parameter
            if not (   is_enrolled(result, user)
                    or self._is_instructor_or_editor(result, user)):
                result = None
        if result is None:
            result = component.queryMultiAdapter((contentUnit, user),
                                                 ICourseInstance)
        return result

    def _is_instructor_or_editor(self, course, user):
        result = False
        if course is not None:
            result = is_course_instructor_or_editor(course, user) \
                  or has_permission(ACT_CONTENT_EDIT, course)
        return result

    # pylint: disable=arguments-differ
    def _do_decorate_external(self, context, result_map):
        entry_ntiid = None
        qsids_to_strip = set()
        assignment_predicate = None

        # When we return page info, we return questions
        # for all of the embedded units as well
        result = get_assessment_items_from_unit(context.contentUnit)

        # Filter out things they aren't supposed to see...currently only
        # assignments...we can only do this if we have a user and a course
        user = self.remoteUser
        unit_ntiid = getattr(context.contentUnit, 'ntiid', None)
        course = self._get_course(context.contentUnit, user)
        if course is not None:
            if not unit_ntiid:
                unit_ntiid = to_external_ntiid_oid(course)
            # Only things in context of a course should have assignments
            predicate = get_course_assessment_predicate_for_user(user, course)
            entry = ICourseCatalogEntry(course, None)
            entry_ntiid = getattr(entry, 'ntiid', None)
            assignment_predicate = predicate

        new_result = {}
        is_instructor = self._is_instructor_or_editor(course, user)
        for ntiid, x in result.iteritems():
            # To keep size down, when we send back assignments or question sets,
            # we don't send back the things they contain as top-level. Moreover,
            # for assignments we need to apply a visibility predicate to the assignment
            # itself.
            if IQuestionBank.providedBy(x):
                qsids_to_strip.update(q.ntiid for q in x.questions)
                new_result[ntiid] = x
            elif IRandomizedQuestionSet.providedBy(x):
                qsids_to_strip.update(q.ntiid for q in x.questions)
                new_result[ntiid] = x
            elif IQuestionSet.providedBy(x):
                # CS:20150729 allow the questions to return along with question set
                # this is for legacy iPad.
                new_result[ntiid] = x
            elif IQSurvey.providedBy(x):
                new_result[ntiid] = x
                qsids_to_strip.update(poll.ntiid for poll in x.questions)
            elif IQAssignment.providedBy(x):
                if assignment_predicate is None:
                    logger.warning("Found assignment (%s) outside of course context "
                                   "in %s; dropping", x, context.contentUnit)
                elif assignment_predicate(x) or is_instructor:
                    # Yay, keep the assignment
                    x = check_assignment(x, user)
                    x = AssignmentProxy(x, entry_ntiid)
                    new_result[ntiid] = x

                # But in all cases, don't echo back the things
                # it contains as top-level items.
                # We are assuming that these are on the same page
                # for now and that they are only referenced by
                # this assignment. We need to fix this
                for assignment_part in x.parts or ():
                    question_set = assignment_part.question_set
                    qsids_to_strip.add(question_set.ntiid)
                    qsids_to_strip.update(
                        q.ntiid for q in question_set.questions
                    )
            else:
                new_result[ntiid] = x

        # remove invalid
        for bad_ntiid in qsids_to_strip:
            new_result.pop(bad_ntiid, None)
        result = new_result.values()

        if result:
            ext_items = to_external_object(result)
            result_map['AssessmentItems'] = ext_items
            result_map[TOTAL] = result_map[ITEM_COUNT] = len(result)
