#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

import os
import sys
import argparse

from zope import component

from zope.component.hooks import site as current_site

from zope.intid.interfaces import IIntIds

from ZODB.POSException import POSError

from nti.app.contentlibrary.utils import yield_content_packages

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.assessment.common import iface_of_assessment

from nti.contentlibrary.interfaces import IContentPackageLibrary

from nti.dataserver.utils import run_with_dataserver
from nti.dataserver.utils.base_script import create_context

from nti.intid.common import removeIntId

from nti.metadata import metadata_queue

from nti.recorder.record import remove_transaction_history

from nti.site.utils import unregisterUtility
from nti.site.hostpolicy import get_all_host_sites

from .._question_map import update_assessment_items_when_modified

def _clear_history(item):
	try:
		remove_transaction_history(item)
	except POSError:
		logger.error('Cannot remove transaction history for %s', item.ntiid)

def _intid_unregister(item, intids):
	try:
		removeIntId(item)
	except POSError:
		iid = intids.queryId(item)
		intids.unregister(item)
		queue = metadata_queue()
		if queue is not None and iid is not None:
			queue.remove(iid)

def _reset_intids(intids):
	logger.info("Removing from intid facility")
	for uid in list(intids.refs):
		try:
			obj = intids.queryObject(uid)
			if IQAssessment.providedBy(obj) or IQInquiry.providedBy(obj):
				_intid_unregister(uid)
		except (TypeError, POSError):
			pass

def _unregister(ntiid, item, intids, registry):
	provided = iface_of_assessment(item)
	unregisterUtility(registry, provided=provided, name=ntiid)
	_clear_history(item)
	_intid_unregister(item, intids)
		
def remove_assessments(registry, intids):
	total = 0
	logger.info('Removing assessments from registry')
	for ntiid, item in list(registry.getUtilitiesFor(IQAssessment)):
		if intids.queryId(item) is None:
			continue
		_unregister(ntiid, item, intids, registry)
		total += 1

	for ntiid, item in list(registry.getUtilitiesFor(IQInquiry)):
		if intids.queryId(item) is None:
			continue
		_unregister(ntiid, item, intids, registry)
		total += 1
		
	logger.info('%s assessments removed', total)

def remove_all_assessments():
	registry = component.getSiteManager()
	intids = component.getUtility(IIntIds)
	remove_assessments(registry, intids)

def _clear_package_containers(package):
	def recur(unit):
		for child in unit.children or ():
			recur(child)
		container = IQAssessmentItemContainer(unit)
		container.clear()
	recur(package)
	main_container = IQAssessmentItemContainer(package)
	main_container.lastModified = 0

def _sync_pacakge_assessments():
	for pacakge in yield_content_packages():
		logger.info("Synchronizing Pacakge Assessments %s", pacakge.ntiid)
		_clear_package_containers(pacakge)
		update_assessment_items_when_modified(pacakge, None)

def _run_job(func, msg):
	ordered = get_all_host_sites()
	for site in ordered:
		logger.info('%s %s...', msg, site.__name__)
		with current_site(site):
			func()

def _process_args(args):
	library = component.queryUtility(IContentPackageLibrary)
	if library is not None:
		library.syncContentPackages()

	logger.info("...")

	if args.reset:
		intids = component.getUtility(IIntIds)
		_reset_intids(intids)

	_run_job(remove_all_assessments, "Removing assessments from")
	_run_job(_sync_pacakge_assessments, "Processing site")

def main():
	arg_parser = argparse.ArgumentParser(description="Reset all assessments")
	arg_parser.add_argument('-v', '--verbose', help="Be Verbose", action='store_true',
							dest='verbose')

	arg_parser.add_argument('-r', '--reset', help="Remove from intids", action='store_true',
							dest='reset')

	args = arg_parser.parse_args()
	env_dir = os.getenv('DATASERVER_DIR')
	if not env_dir or not os.path.exists(env_dir) and not os.path.isdir(env_dir):
		raise IOError("Invalid dataserver environment root directory")

	conf_packages = ('nti.appserver',)
	context = create_context(env_dir, with_library=True)

	run_with_dataserver(environment_dir=env_dir,
						verbose=args.verbose,
						xmlconfig_packages=conf_packages,
						context=context,
						minimal_ds=True,
						function=lambda: _process_args(args))
	sys.exit(0)

if __name__ == '__main__':
	main()
