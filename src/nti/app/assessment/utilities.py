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

from zope.security.interfaces import IPrincipal

from zope.intid import IIntIds

from nti.app.authentication import get_remote_user

from nti.assessment.randomized.interfaces import IPrincipalSeedSelector

from nti.dataserver.users import User
from nti.dataserver.interfaces import IUser

def get_user(user=None):
	if user is None:
		user = get_remote_user()
	elif IPrincipal.providedBy(user):
		user = user.id
	if user is not None and not IUser.providedBy(user):
		user = User.get_user(str(user))
	return user

def get_uid(context):
	result = component.getUtility(IIntIds).getId(context)
	return result

@interface.implementer(IPrincipalSeedSelector)
class PrincipalSeedSelector(object):

	def __call__(self, principal=None):
		user = get_user(principal)
		if user is not None:
			return get_uid(user)
		return None
