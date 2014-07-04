#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function, unicode_literals, absolute_import
__docformat__ = "restructuredtext en"

# disable: accessing protected members, too many methods
# pylint: disable=W0212,R0904

from hamcrest import assert_that
from hamcrest import is_
from hamcrest import none
from hamcrest import same_instance

from zope import component

from nti.assessment import interfaces as asm_interfaces

from nti.contentlibrary import interfaces as lib_interfaces
from .. import _question_map as qm_module

from nti.app.testing.application_webtest import ApplicationLayerTest
from nti.appserver.contentlibrary.tests import CourseTestContentApplicationTestLayer

class TestApplicationQuestionsRegistered(ApplicationLayerTest):
	layer = CourseTestContentApplicationTestLayer

	def test_check_questions_registered(self):
		library = component.getUtility(lib_interfaces.IContentPackageLibrary)
		content_package = library.contentPackages[0]

		# The question and sets are registered, and are the same instance
		question_set = component.getUtility( asm_interfaces.IQuestionSet,
											 name="tag:nextthought.com,2011-10:NTI-NAQ-CourseTestContent.naq.set.qset:QUIZ1_aristotle" )
		for question in question_set.questions:
			assert_that( question, is_( same_instance( component.getUtility( asm_interfaces.IQuestion,
																			 name=question.ntiid ))))
		# remove
		# XXX: test hygiene: this has after effects!
		qm_module.remove_assessment_items_from_oldcontent(content_package, None)

		# And everything is gone.
		assert_that( component.queryUtility( asm_interfaces.IQuestionSet, question_set.ntiid ),
					 is_( none() ) )
