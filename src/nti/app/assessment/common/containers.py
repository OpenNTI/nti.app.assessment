#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import component

from zope.intid.interfaces import IIntIds

from nti.app.assessment.common.evaluations import get_course_assessment_items
from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object

from nti.app.assessment.index import get_evaluation_catalog

from nti.assessment.interfaces import IQAssignment

logger = __import__('logging').getLogger(__name__)


def get_outline_evaluation_containers(obj):
    """
    For the given evaluation, return any unique containers which might
    be found in a course outline (question sets, question banks,
    assignments, and surveys.).
    """
    if obj.ntiid is None:
        # Tests
        return
    assigment_question_sets = set()
    containers = get_containers_for_evaluation_object(obj,
                                                      include_question_sets=True)

    # Gather assignment question sets and remove them.
    for container in containers or ():
        if IQAssignment.providedBy(container):
            assigment_question_sets.update(
                x.ntiid for x in container.iter_question_sets()
            )

    if assigment_question_sets and containers:
        results = []
        for container in containers:
            if container.ntiid not in assigment_question_sets:
                results.append(container)
    else:
        results = containers
    return results


def index_course_package_assessments(course):
    """
    Index the given course's package assessments.
    """
    catalog = get_evaluation_catalog()
    intids = component.getUtility(IIntIds)
    assessment_items = get_course_assessment_items(course)
    count = 0
    for item in assessment_items or ():
        doc_id = intids.queryId(item)
        if doc_id is not None:
            catalog.index_doc(doc_id, item)
            count += 1
    return count
