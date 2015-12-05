#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.appserver.ugd_edit_views import UGDPutView

class AssessmentPutView(UGDPutView):

	def readInput(self, value=None):
		# TODO Validations?
		result = UGDPutView.readInput(self, value=value)
		result.pop('ntiid', None)
		result.pop('NTIID', None)
		return result
