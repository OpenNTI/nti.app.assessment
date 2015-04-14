#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.dataserver.users import User

from .adapters import _histories_for_course
from .adapters import _history_for_user_in_course

def move_user_assignment_from_course_to_course(user, source, target, verbose=True):
	result = []
	log = logger.info if verbose else logger.debug
	
	new_history = _history_for_user_in_course(target, user, create=True)
	old_history = _history_for_user_in_course(source, user, create=False) or ()
	
	for k in list(old_history): # we are changing
		item = old_history[k]
		
		## JAM: do a full delete/re-add so that ObjectAdded event gets fired, 
		## because that's where auto-grading takes place
		del old_history[k]
		assert item.__name__ is None
		assert item.__parent__ is None
		
		if k in new_history:
			log("Skipped moving %s for %s from %s to %s", k, user, 
				source.__name__, target.__name__)
			continue

		result.append(k)
		new_history[k] = item

		log("Moved %s for %s from %s to %s", k, user,
			 source.__name__, target.__name__)
	return result

def move_assignment_histories_from_course_to_course(source, target, verbose=True):
	result = {}
	histories = _histories_for_course(source, False)
	for username in histories:
		user = User.get_user(username)
		if user is not None:
			moves = move_user_assignment_from_course_to_course(user=user,
															   source=source,
															   target=target,
															   verbose=verbose)
			result[username] =  moves
	return result
