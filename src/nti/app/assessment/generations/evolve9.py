#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

generation = 9

from zope import component

from zope.component.hooks import site as current_site

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion 
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet

from nti.contentlibrary.indexed_data import get_library_catalog

from nti.site.hostpolicy import get_all_host_sites

def do_evolve(context, generation=generation):
	conn = context.connection
	ds_folder = conn.root()['nti.dataserver']

	with current_site(ds_folder):
		assert	component.getSiteManager() == ds_folder.getSiteManager(), \
				"Hooks not installed?"

		catalog = get_library_catalog()
		for site in get_all_host_sites():
			with current_site(site):
				registry = component.getSiteManager()

				# index question sets
				for asg_ntiid, asg in list(registry.getUtilitiesFor(IQAssignment)):
					for part in asg.parts:
						question_set = part.question_set
						q_set_ntiid = question_set.ntiid
						question_set = registry.getUtility(IQuestionSet, name=q_set_ntiid)
						catalog.index(question_set, container_ntiids=(asg_ntiid,))
						
						# index questions
						for question in question_set.questions:
							question = registry.getUtility(IQuestion, name=question.ntiid)
							catalog.index(question, 
										  container_ntiids=(asg_ntiid, q_set_ntiid))
							
				# index polls
				for survey_ntiid, survey in list(registry.getUtilitiesFor(IQSurvey)):
					for poll in survey.questions:
						poll = registry.getUtility(IQPoll, name=poll.ntiid)
						catalog.index(poll, container_ntiids=(survey_ntiid,))
							
	logger.info('contenttypes.courses evolution %s done.', generation)

def evolve(context):
	"""
	Evolve to generation 13 by making date context persistent mappings
	"""
	do_evolve(context, generation)
