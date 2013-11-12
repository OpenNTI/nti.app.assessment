#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment.

$Id$
"""

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import pyramid.httpexceptions as hexc
from pyramid.view import view_config

from nti.dataserver import authorization as nauth

# TODO: Break these direct dependencies....
from nti.appserver.contentlibrary.library_views import PAGE_INFO_MT_JSON
# ... this in particular could be a view.
from nti.appserver.contentlibrary.library_views import find_page_info_view_helper

####
## In pyramid 1.4, there is some minor wonkiness with the accept= request predicate.
## Your view can get called even if no Accept header is present if all the defined
## views include a non-matching accept predicate. Stil, this is much better than
## the behaviour under 1.3.
####
_view_defaults = dict( route_name='objects.generic.traversal',
					   renderer='rest',
					   context='nti.assessment.interfaces.IQuestion',
					   permission=nauth.ACT_READ,
					   request_method='GET' )
@view_config(accept=PAGE_INFO_MT_JSON.encode('ascii'), **_view_defaults)
def pageinfo_from_question_view( request ):
	assert request.accept
	# questions are now generally held within their containing IContentUnit,
	# but some old tests don't parent them correctly, using strings
	content_unit_or_ntiid = request.context.__parent__
	return find_page_info_view_helper( request, content_unit_or_ntiid )


@view_config(accept=b'application/vnd.nextthought.link+json', **_view_defaults)
def get_question_view_link( request ):
	# Not supported.
	return hexc.HTTPBadRequest()

@view_config(accept=b'', 		# explicit empty accept, else we get a ConfigurationConflict
			 **_view_defaults)	# and/or no-Accept header goes to the wrong place
@view_config(**_view_defaults)
def get_question_view( request ):
	return request.context

del _view_defaults
