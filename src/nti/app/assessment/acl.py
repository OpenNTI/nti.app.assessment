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

from nti.assessment.interfaces import IQAssessment

from nti.common.property import Lazy

from nti.dataserver.interfaces import ALL_PERMISSIONS

from nti.dataserver.interfaces import IACLProvider

from nti.dataserver.authorization import ROLE_ADMIN
from nti.dataserver.authorization import ROLE_CONTENT_EDITOR

from nti.dataserver.authorization_acl import ace_allowing
from nti.dataserver.authorization_acl import acl_from_aces

@component.adapter(IQAssessment)
@interface.implementer(IACLProvider)
class AssessmentACLProvider(object):
	"""
	Provides the basic ACL for an asessment.
	"""

	def __init__(self, context):
		self.context = context

	@property
	def __parent__(self):
		# See comments in nti.dataserver.authorization_acl:has_permission
		return self.context.__parent__

	@Lazy
	def __acl__(self):
		aces = [ ace_allowing(ROLE_ADMIN, ALL_PERMISSIONS, self),
				 ace_allowing(ROLE_CONTENT_EDITOR, ALL_PERMISSIONS, self)]
		result = acl_from_aces(aces)
		return result
