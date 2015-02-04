#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from nti.monkey import relstorage_patch_all_except_gevent_on_import
relstorage_patch_all_except_gevent_on_import.patch()

import os

from zope.container.contained import Contained
from zope.configuration import xmlconfig, config
from zope.dottedname import resolve as dottedname

import zope.browserpage

from z3c.autoinclude.zcml import includePluginsDirective

class PluginPoint(Contained):

	def __init__(self, name):
		self.__name__ = name

PP_APP = PluginPoint('nti.app')
PP_APP_SITES = PluginPoint('nti.app.sites')
PP_APP_PRODUCTS = PluginPoint('nti.app.products')

def create_context(env_dir=None, with_library=True):
	etc = os.getenv('DATASERVER_ETC_DIR') or os.path.join(env_dir, 'etc')
	etc = os.path.expanduser(etc)

	context = config.ConfigurationMachine()
	xmlconfig.registerCommonDirectives(context)

	slugs = os.path.join(etc, 'package-includes')
	if os.path.exists(slugs) and os.path.isdir(slugs):
		package = dottedname.resolve('nti.dataserver')
		context = xmlconfig.file('configure.zcml', package=package, context=context)
		xmlconfig.include(context, files=os.path.join(slugs, '*.zcml'),
						  package='nti.appserver')

	if with_library:
		library_zcml = os.path.join(etc, 'library.zcml')
		if not os.path.exists(library_zcml):
			raise Exception("Could not locate library zcml file %s", library_zcml)
		xmlconfig.include(context, file=library_zcml, package='nti.appserver')
		
	# Include zope.browserpage.meta.zcm for tales:expressiontype
	# before including the products
	xmlconfig.include(context, file="meta.zcml", package=zope.browserpage)

	# include plugins
	includePluginsDirective(context, PP_APP)
	includePluginsDirective(context, PP_APP_SITES)
	includePluginsDirective(context, PP_APP_PRODUCTS)
	
	return context
