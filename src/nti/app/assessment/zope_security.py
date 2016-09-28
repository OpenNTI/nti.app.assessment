#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Adapters for application-level events.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.securitypolicy.interfaces import Deny
from zope.securitypolicy.interfaces import IRolePermissionMap

from zope.securitypolicy.rolepermission import AnnotationRolePermissionManager

from nti.app.assessment.interfaces import IUsersCourseAssignmentHistories

from nti.dataserver.authorization import ROLE_CONTENT_ADMIN_NAME

@component.adapter(IUsersCourseAssignmentHistories)
@interface.implementer(IRolePermissionMap)
class AssignmentHistoriesRolePermissionManager(AnnotationRolePermissionManager):
	"""
	A Zope `IRolePermissionMap` that denies any access by global
	content admins to the underlying submission structure.
	"""

	def __bool__(self):
		return True
	__nonzero__ = __bool__

	def getRolesForPermission(self, perm):
		result = []
		super_roles = super( AssignmentHistoriesRolePermissionManager, self ).getRolesForPermission( perm )
		for role, setting in super_roles:
			if role != ROLE_CONTENT_ADMIN_NAME:
				result.append( (role, setting) )
		result.append( (ROLE_CONTENT_ADMIN_NAME, Deny) )
		return result
