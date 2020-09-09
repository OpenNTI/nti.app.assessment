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


class IQCreationContext(interface.Interface):
    """
    Provides a way to reference an object in which the associated
    object was created.  E.g. this could be annotated on a poll to
    reference the survey it was created for.
    """

    NTIID = ValidNTIID(title=u"The NTIID of the object (context) in which "
                             u"the associated object was created",
                       required=False)


class IQConstituentCleaner(interface.Interface):
    """
    Provides a way to clean up consituents that are part of the same
    creation context when the primary object is removed.
    """

    def clean_consitutents(candidates):
        """
        Provided a set of candidates, remove any created in the
        associated context.
        """