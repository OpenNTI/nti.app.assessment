#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from pyramid import httpexceptions as hexc

from six.moves.urllib_parse import unquote

from zope import component
from zope import interface

from zope.container.contained import Contained

from zope.traversing.interfaces import IPathAdapter

from nti.assessment.interfaces import IQEvaluation

from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance

logger = __import__('logging').getLogger(__name__)


class _BaseCourseEvaluationPathAdapter(Contained):

    adapter = None

    def __init__(self, context, request=None):
        self.request = request
        self.__parent__ = context
        # pylint: disable=not-callable
        self.context = self.adapter(context)

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
    __name__ = u'Assessments'
    adapter = ICourseInstance


@interface.implementer(IPathAdapter)
class _CourseInquiriesPathAdapter(_BaseCourseEvaluationPathAdapter):
    __name__ = u'CourseInquiries'
    adapter = ICourseInstance


@interface.implementer(IPathAdapter)
class _ContentPackageAssessmentsPathAdapter(_BaseCourseEvaluationPathAdapter):
    __name__ = u'Assessments'
    adapter = IContentPackage


@interface.implementer(IPathAdapter)
class _ContentPackageInquiriesPathAdapter(_BaseCourseEvaluationPathAdapter):
    __name__ = u'PackageInquiries'
    adapter = IContentPackage
