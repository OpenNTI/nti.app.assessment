#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessment

from nti.common.property import Lazy

from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_ADMIN

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.interfaces import IACLProvider

@interface.implementer(IACLProvider)
class EvaluationACLProvider(object):

	def __init__(self, context):
		self.context = context

	@property
	def __parent__(self):
		return self.context.__parent__

	@Lazy
	def __acl__(self):
		aces = [ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, type(self)),
				ace_allowing(ROLE_CONTENT_ADMIN, ALL_PERMISSIONS, type(self))]
		result = acl_from_aces(aces)
		return result

@component.adapter(IQAssessment)
@interface.implementer(IACLProvider)
class AssessmentACLProvider(EvaluationACLProvider):
	"""
	Provides the basic ACL for an asessment.
	"""
	pass

@component.adapter(IQInquiry)
@interface.implementer(IACLProvider)
class InquiryACLProvider(EvaluationACLProvider):
	"""
	Provides the basic ACL for an inquiry.
	"""
	pass
