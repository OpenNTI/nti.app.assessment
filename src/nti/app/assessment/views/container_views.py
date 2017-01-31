#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division

__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import VIEW_QUESTION_CONTAINERS

from nti.app.assessment.common import get_outline_evaluation_containers

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.assessment.interfaces import IQuestion

from nti.dataserver import authorization as nauth

from nti.externalization.externalization import to_external_object

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS
TOTAL = StandardExternalFields.TOTAL
ITEM_COUNT = StandardExternalFields.ITEM_COUNT


@view_config(context=IQuestion)
@view_defaults(route_name='objects.generic.traversal',
               renderer='rest',
               name=VIEW_QUESTION_CONTAINERS,
               permission=nauth.ACT_CONTENT_EDIT)
class QuestionContainersView(AbstractAuthenticatedView):
    """
    Fetch all question_sets/assignments holding our given context.
    A `course` param can be given that narrows the scope of the result,
    otherwise, results from all courses will be returned.
    """

    def __call__(self):
        result = LocatedExternalDict()
        result[ITEMS] = assessments = list()
        containers = get_outline_evaluation_containers(self.context)
        containers = [to_external_object(x, name="summary") for x in containers]
        assessments.extend(containers)
        result[ITEM_COUNT] = result[TOTAL] = len(containers)
        return result
