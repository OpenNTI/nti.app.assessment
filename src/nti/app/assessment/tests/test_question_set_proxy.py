#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from hamcrest import is_
from hamcrest import is_not
from hamcrest import assert_that
from hamcrest import instance_of

from ZODB.interfaces import IConnection

from zope import interface

from nti.app.assessment.tests import AssessmentLayerTest

from nti.assessment.randomized.interfaces import IQRandomizedPart
from nti.assessment.randomized.interfaces import IRandomizedPartsContainer

from nti.assessment.parts import QMultipleChoicePart

from nti.assessment.question import QQuestion
from nti.assessment.question import QQuestionSet

from nti.assessment.randomized_proxy import RandomizedPartProxy
from nti.assessment.randomized_proxy import QuestionRandomizedPartsProxy

from nti.assessment.solution import QMultipleChoiceSolution

from nti.dataserver.tests import mock_dataserver

from nti.dataserver.tests.mock_dataserver import WithMockDS


class TestQuestionSet(AssessmentLayerTest):

    @WithMockDS
    def test_proxy(self):
        """
        Validate a randomized proxy question set will not 'change'
        objects as it proxies the underlying questions and parts.
        """
        with mock_dataserver.mock_db_trans():
            part = QMultipleChoicePart(solutions=(QMultipleChoiceSolution(value=1),))
            question = QQuestion(parts=(part,))
            question_set = QQuestionSet(questions=(question,))

            def check_elements(randomized=False):
                rand_check = is_ if randomized else is_not
                for found_question in (tuple(question_set.Items)[0],
                                       question_set.questions[0],
                                       question_set[0]):
                    assert_that(found_question, rand_check(instance_of(QuestionRandomizedPartsProxy)))
                    for found_part in (found_question.parts[0],
                                       found_question[0]):
                        assert_that(found_part,
                                    rand_check(instance_of(RandomizedPartProxy)))
                        assert_that(found_part.randomized, is_(randomized))
                        assert_that(IQRandomizedPart.providedBy(found_part),
                                    is_(randomized))

            check_elements(randomized=False)
            interface.alsoProvides(question_set, IRandomizedPartsContainer)
            check_elements(randomized=True)
            IConnection(self.ds.root).add(question_set)

        with mock_dataserver.mock_db_trans():
            assert_that(question_set._p_changed, is_not(True))
            for question in question_set.Items:
                assert_that(question._p_changed, is_not(True))
                for part in question.parts:
                    assert_that(part._p_changed, is_not(True))
