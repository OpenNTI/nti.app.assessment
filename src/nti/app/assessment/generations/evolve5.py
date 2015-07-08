#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 5

from .evolve3 import do_evolve

def evolve(context):
	"""
	Evolve to generation 5 recreating assessment index.
	"""
	do_evolve(context)
