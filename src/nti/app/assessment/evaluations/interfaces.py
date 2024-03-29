#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

from zope import interface

from nti.contenttypes.courses.interfaces import ICourseSectionExporter
from nti.contenttypes.courses.interfaces import ICourseSectionImporter

from nti.ntiids.schema import ValidNTIID

logger = __import__('logging').getLogger(__name__)


class ICourseEvaluationsSectionExporter(ICourseSectionExporter):
    pass


class ICourseEvaluationsSectionImporter(ICourseSectionImporter):
    pass


class ICourseEvaluationExporter(interface.Interface):
    """
    Export an evaluation object; an alternative to a general named
    externalizer that allows for passing export params such as the
    filer
    """

    def export(evaluation, filer, backup=True, salt=None):
        """
        Export the specified evaluation

        :param evaluation: Evaluation to export
        :param filer: External source filer
        :param backup: backup flag
        :param salt: ntiid salt
        """


class IImplicitlyDeletable(interface.Interface):
    """
    Marker interface indicating we can safely remove the object
    when there are no more references to it, e.g. a poll created
    in the context of a survey.
    """


IImplicitlyDeletable.setTaggedValue('_ext_is_marker_interface', True)
