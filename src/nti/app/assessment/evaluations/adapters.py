#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import time

from zope import component
from zope import interface

from zope.annotation.interfaces import IAnnotations

from ZODB.interfaces import IConnection

from pyramid.interfaces import IRequest

from nti.app.assessment.adapters import course_from_context_lineage

from nti.app.assessment.evaluations.model import CourseEvaluations
from nti.app.assessment.evaluations.model import ContentPackageEvaluations

from nti.app.assessment.interfaces import IQEvaluations

from nti.assessment.interfaces import IQEditableEvaluation

from nti.contentlibrary.interfaces import IEditableContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.traversal.traversal import find_interface
from nti.traversal.traversal import ContainerAdapterTraversable


@component.adapter(ICourseInstance)
@interface.implementer(IQEvaluations)
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
@component.adapter(IQEvaluations)
def course_from_item_lineage(item):
    return course_from_context_lineage(item, validate=True)


@interface.implementer(ICourseInstance)
@component.adapter(IQEditableEvaluation)
def editable_evaluation_to_course(resource):
    return find_interface(resource, ICourseInstance, strict=False)


@component.adapter(ICourseInstance, IRequest)
def evaluations_for_course_path_adapter(course, _):
    return evaluations_for_course(course)


@interface.implementer(IQEvaluations)
@component.adapter(IEditableContentPackage) 
def evaluations_for_package(package):
    try:
        result = package._package_evaluations
    except AttributeError:
        result = package._package_evaluations = ContentPackageEvaluations()
        result.createdTime = time.time()
        result.__parent__ = package
        result.__name__ = '_package_evaluations'
    return result


@component.adapter(IQEvaluations)
@interface.implementer(IEditableContentPackage)
def package_from_item_lineage(item):
    return item.__parent__


@component.adapter(IQEditableEvaluation)
@interface.implementer(IEditableContentPackage)
def editable_evaluation_to_package(resource):
    return find_interface(resource, IEditableContentPackage, strict=False)


@component.adapter(IEditableContentPackage, IRequest)
def evaluations_for_package_path_adapter(package, _):
    return evaluations_for_package(package)


@component.adapter(IQEvaluations, IRequest)
class EvaluationsTraversable(ContainerAdapterTraversable):

    def traverse(self, key, remaining_path):
        return super(EvaluationsTraversable, self).traverse(key, remaining_path)
