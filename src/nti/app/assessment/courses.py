#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id: savepoint.py 94760 2016-08-19 16:23:49Z carlos.sanchez $
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.container.contained import Contained

from zope.location.interfaces import LocationError

from zope.traversing.interfaces import IPathAdapter

from pyramid.interfaces import IRequest

from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.contenttypes.courses.interfaces import ICourseInstance

from nti.traversal.traversal import ContainerAdapterTraversable

@interface.implementer(IPathAdapter)
class _CourseAssessmentsPathAdapter(Contained):

	__name__ = 'Assessments'

	def __init__(self, context, request=None):
		self.request = request
		self.__parent__ = context
		self.context = ICourseInstance(context, None)

@component.adapter(_CourseAssessmentsPathAdapter, IRequest)
class _CourseAssessmentsTraversable(ContainerAdapterTraversable):

	def traverse(self, key, remaining_path):
		container = IQAssessmentItemContainer(self.context)
		assesment = component.queryUtility(IQAssessment, name=key)
		if key in container and assesment is not None:
			return assesment
		raise LocationError(self.context, key)
