#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.app.renderers.decorators import AbstractAuthenticatedRequestAwareDecorator
				
class _IPad110NoSubmitPartAdjuster(AbstractAuthenticatedRequestAwareDecorator):
	"""
	Here is a bit of background first. The CS1323 has a bunch of
	"no-submit" assignments for things that aren't submitted on the
	platform (turings craft, problets, etc). These no submit
	assignments were marked up in the content on a page titled
	"Grades" beneath each lesson that had no-submit assignments
	content nodes. Because these were no_submits the webapp handles
	clicks on them in a special way however when written in December
	the pad was not. The pad just takes you to whatever content page
	is appropriate for the assignment just like it does for "normal"
	assignments or question sets. Come January that was a problem
	because clicking the no-submit assignment on the pad just
	presented a blank page to the user. At the time, to prevent this,
	we coded up some filtering logic to filter these empty assignments
	out of the overview if they had no parts. In retrospect we should
	have just changed how we authored the content but hindsights
	always 20/20.

	This is now causing issues because they want to change all the no
	submits to actually have a content page like a normal assignment.
	Basically a page that gives the instructions on how to do the
	no-submit assignment (rather than a separate link like is used
	now). This all works fine except that these assignments have no
	parts and so they don't show up on the overview. I checked on my
	side and it seems like if I can get past the filtering things work
	just as we would expect. We obviously won't have something in the
	store come monday that works with this content so I was wondering
	if there was something we could do on the server side [1] to help
	work around this. To get past the pad's filtering these
	Assignments need to have a non-empty parts array in the response
	of the AssignmentsByOutlineNode call.

	Something like :

	parts: [{Class: AssignmentPart}]

	would do it from what I can tell.
	"""

	_BAD_UAS = ( "NTIFoundation DataLoader NextThought/1.0",
				 "NTIFoundation DataLoader NextThought/1.1.0",
				 "NTIFoundation DataLoader NextThought/1.1.1")

	def _predicate(self, context, result):
		if not context.no_submit or context.parts:
			return False

		ua = self.request.environ.get('HTTP_USER_AGENT', '')
		if not ua:
			return False

		for bua in self._BAD_UAS:
			if ua.startswith(bua):
				return True

	def _do_decorate_external(self, context, result):
		result['parts'] = [{'Class': 'AssignmentPart'}]
					