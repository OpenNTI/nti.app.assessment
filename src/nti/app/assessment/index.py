#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zc.intid import IIntIds

from zope import interface
from zope.location import locate

from zope.catalog.interfaces import ICatalogIndex

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
    
from nti.dataserver.interfaces import ICreatedUsername
from nti.dataserver.interfaces import IMetadataCatalog

from nti.zope_catalog.catalog import Catalog
from nti.zope_catalog.index import NormalizationWrapper
from nti.zope_catalog.index import ValueIndex as RawValueIndex
from nti.zope_catalog.index import AttributeValueIndex as ValueIndex

from nti.zope_catalog.string import StringTokenNormalizer

from .interfaces import IUsersCourseSurveyItem

CATALOG_NAME = 'nti.dataserver.++etc++survey-catalog'

IX_COURSE = 'course'
IX_SURVEY_ID = 'surveyId'
IX_CREATOR = IX_STUDENT = IX_USERNAME = 'creator'

class SurveyIdIndex(ValueIndex):
    default_field_name = 'surveyId'
    default_interface = IUsersCourseSurveyItem

class CreatorRawIndex(RawValueIndex):
    pass

def CreatorIndex(family=None):
    return NormalizationWrapper(field_name='creator_username',
                                interface=ICreatedUsername,
                                index=CreatorRawIndex(family=family),
                                normalizer=StringTokenNormalizer())

class ValidatingCatalogEntryID(object):
    """
    The "interface" we adapt to to find the submission course.
    """

    __slots__ = (b'ntiid',)

    def __init__(self, obj, default=None):
        grade = IUsersCourseSurveyItem(obj, default)
        entry = ICourseCatalogEntry(ICourseInstance(grade, None), None)
        if entry is not None:
            self.ntiid = unicode(entry.ntiid)

    def __reduce__(self):
        raise TypeError()

class CatalogEntryIDIndex(ValueIndex):
    default_field_name = 'ntiid'
    default_interface = ValidatingCatalogEntryID

@interface.implementer(IMetadataCatalog)
class MetadataSurveyCatalog(Catalog):
    
    super_index_doc = Catalog.index_doc

    def index_doc(self, docid, ob):
        pass

    def force_index_doc(self, docid, ob):
        self.super_index_doc( docid, ob)

def install_survey_catalog(site_manager_container, intids=None):
    lsm = site_manager_container.getSiteManager()
    if intids is None:
        intids = lsm.getUtility(IIntIds)

    catalog = lsm.queryUtility(IMetadataCatalog, name=CATALOG_NAME)
    if catalog is not None:
        return catalog

    catalog = MetadataSurveyCatalog(family=intids.family)
    locate(catalog, site_manager_container, CATALOG_NAME)
    intids.register( catalog )
    lsm.registerUtility(catalog, provided=IMetadataCatalog, name=CATALOG_NAME )

    for name, clazz in ( (IX_CREATOR, CreatorIndex),
                         (IX_SURVEY_ID, SurveyIdIndex), 
                         (IX_COURSE, CatalogEntryIDIndex) ):
        index = clazz( family=intids.family )
        assert ICatalogIndex.providedBy(index)
        intids.register( index )
        locate(index, catalog, name)
        catalog[name] = index

    return catalog
