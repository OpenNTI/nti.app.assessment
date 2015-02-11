#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from .adapters import _history_for_user_in_course

def move_user_assignment_from_course_to_course(user, source, target, verbose=True):
	result = []
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
			if verbose:
				logger.info("Skipped moving %s for %s from %s to %s", k, user, 
							source.__name__, target.__name__)
			continue

		result.append(k)
		new_history[k] = item
		if verbose:
			logger.info("Moved %s for %s from %s to %s", k, user,
						source.__name__, target.__name__)
	return result
