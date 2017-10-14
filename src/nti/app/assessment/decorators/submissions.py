#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from zope import interface

from nti.assessment.interfaces import IPlaceholderAssignmentSubmission

from nti.externalization.interfaces import IExternalMappingDecorator

from nti.externalization.singleton import Singleton

logger = __import__('logging').getLogger(__name__)


@interface.implementer(IExternalMappingDecorator)
class _SyntheticSubmissionDecorator(Singleton):
    """
    Decorate placeholder submissions as synthetic submissions.
    """

    def decorateExternalMapping(self, item, result_map):
        submission = item.Submission
        is_synth = IPlaceholderAssignmentSubmission.providedBy(submission)
        result_map['SyntheticSubmission'] = is_synth
