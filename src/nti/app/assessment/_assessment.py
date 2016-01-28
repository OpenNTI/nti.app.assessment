#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.app.assessment.adapters import _histories_for_course
from nti.app.assessment.adapters import _history_for_user_in_course

from nti.app.assessment.metadata import _metadata_for_user_in_course
from nti.app.assessment.metadata import _metadatacontainer_for_course

from nti.dataserver.users import User

def _container_mover(old_container, new_container, verbose=True,
					 user=None, source=None, target=None):
	result = []
	log = logger.info if verbose else logger.debug
	for k in list(old_container):  # we are changing
		item = old_container[k]

		del old_container[k]
		assert item.__name__ is None
		assert item.__parent__ is None

		if k in new_container:
			log("Skipped moving %s for %s from %s to %s", k, user, source, target)
			continue

		result.append(k)
		new_container[k] = item

		log("Moved %s for %s from %s to %s", k, user, source, target)

	return result

def move_user_assignment_from_course_to_course(user, source, target, verbose=True):
	new_history = _history_for_user_in_course(target, user, create=True)
	old_history = _history_for_user_in_course(source, user, create=False) or ()
	result = _container_mover(old_history, new_history, verbose=verbose, user=user,
							  source=source.__name__, target=target.__name__)
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
			result[username] = moves
	return result

def move_user_metadata_from_course_to_course(user, source, target, verbose=True):
	new_metadata = _metadata_for_user_in_course(target, user, create=True)
	old_metadata = _metadata_for_user_in_course(source, user, create=False) or ()
	result = _container_mover(old_metadata, new_metadata, verbose=verbose, user=user,
							  source=source.__name__, target=target.__name__)
	return result

def move_metadata_from_course_to_course(source, target, verbose=True):
	result = {}
	histories = _metadatacontainer_for_course(source, False)
	for username in histories:
		user = User.get_user(username)
		if user is not None:
			moves = move_user_metadata_from_course_to_course(user=user,
															 source=source,
															 target=target,
															 verbose=verbose)
			result[username] = moves
	return result
