#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from ZODB.interfaces import IConnection

from pyramid.interfaces import IRequest

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.evaluations.model import CourseEvaluations

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.assessment.interfaces import IQEditableEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable


@component.adapter(ICourseInstance)
@interface.implementer(ICourseEvaluations)
def evaluations_for_course(course, create=True):
    result = None
    annotations = IAnnotations(course)
    try:
        KEY = 'CourseEvaluations'
        result = annotations[KEY]
    except KeyError:
        if create:
            result = CourseEvaluations()
            annotations[KEY] = result
            result.__name__ = KEY
            result.__parent__ = course
            # Deterministically add to our course db.
            # Sectioned courses would give us multiple
            # db error for some reason.
            IConnection(course).add(result)
    return result


@interface.implementer(ICourseInstance)
@component.adapter(ICourseEvaluations)
def course_from_item_lineage(item):
    return course_from_context_lineage(item, validate=True)


@interface.implementer(ICourseInstance)
@component.adapter(IQEditableEvaluation)
def editable_evaluation_to_course(resource):
    return find_interface(resource, ICourseInstance, strict=False)


@component.adapter(ICourseInstance, IRequest)
def evaluations_for_course_path_adapter(course, request):
    return evaluations_for_course(course)


@component.adapter(ICourseEvaluations, IRequest)
class CourseEvaluationsTraversable(ContainerAdapterTraversable):

    def traverse(self, key, remaining_path):
        return super(CourseEvaluationsTraversable, self).traverse(key, remaining_path)
