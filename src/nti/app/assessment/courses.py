#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from urllib import unquote

from zope import component
from zope import interface

from zope.container.contained import Contained

from zope.traversing.interfaces import IPathAdapter

from pyramid import httpexceptions as hexc

from nti.assessment.interfaces import IQEvaluation

from nti.contenttypes.courses.interfaces import ICourseInstance


class _BaseCourseEvaluationPathAdapter(Contained):

    def __init__(self, context, request=None):
        self.request = request
        self.__parent__ = context
        self.context = ICourseInstance(context)

    def __getitem__(self, key):
        if not key:
            raise hexc.HTTPNotFound()
        ntiid = unquote(key)
        assesment = component.queryUtility(IQEvaluation, name=ntiid)
        if assesment is not None:
            return assesment
        raise KeyError(ntiid)


@interface.implementer(IPathAdapter)
class _CourseAssessmentsPathAdapter(_BaseCourseEvaluationPathAdapter):
    __name__ = 'Assessments'


@interface.implementer(IPathAdapter)
class _CourseInquiriesPathAdapter(_BaseCourseEvaluationPathAdapter):
    __name__ = 'CourseInquiries'
