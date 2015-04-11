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

from .interfaces import IUsersCourseInquiryItem
from .interfaces import IUsersCourseAssignmentHistoryItem

CATALOG_NAME = 'nti.dataserver.++etc++inquiry-catalog'

IX_ITEM_ID = 'itemId'
IX_ITEM_MIME_TYPE = 'mimeType'
IX_ENTRY = IX_COURSE = 'course'
IX_CREATOR = IX_STUDENT = IX_USERNAME = 'creator'

class CreatorRawIndex(RawValueIndex):
    pass

def CreatorIndex(family=None):
    return NormalizationWrapper(field_name='creator_username',
                                interface=ICreatedUsername,
                                index=CreatorRawIndex(family=family),
                                normalizer=StringTokenNormalizer())

class ValidatingCatalogEntryID(object):

    __slots__ = (b'ntiid',)

    @classmethod
    def _entry(cls, obj):
        for iface in (IUsersCourseInquiryItem, IUsersCourseAssignmentHistoryItem):
            item = iface(obj, None)
            if item is not None:
                course = ICourseInstance(item, None)
                entry = ICourseCatalogEntry(course, None)
                return entry
        return None

    def __init__(self, obj, default=None):
        entry = self._entry(obj, default)
        if entry is not None:
            self.ntiid = unicode(entry.ntiid)

    def __reduce__(self):
        raise TypeError()

class CatalogEntryIDIndex(ValueIndex):
    default_field_name = 'ntiid'
    default_interface = ValidatingCatalogEntryID

class ValidatingItemID(object):
 
    __slots__ = (b'itemId',)

    def __init__(self, obj, default=None):
        if  IUsersCourseAssignmentHistoryItem.providedBy(obj) or \
            IUsersCourseInquiryItem.providedBy(obj):
            self.itemId = self.__name__

    def __reduce__(self):
        raise TypeError()
    
class ItemIdIndex(ValueIndex):
    default_field_name = 'itemId'
    default_interface = ValidatingItemID
    
class ValidatingItemMimeType(object):
 
    __slots__ = (b'mimeType',)

    def __init__(self, obj, default=None):
        try:
            if IUsersCourseAssignmentHistoryItem.providedBy(obj):
                self.mimeType = getattr(obj.Assignment, 'mimeType', None)
            elif IUsersCourseInquiryItem.providedBy(obj):
                self.mimeType = getattr(obj.Inquiry, 'mimeType', None)
        except (AttributeError, TypeError):
            pass
        
    def __reduce__(self):
        raise TypeError()
    
class ItemMimeTypeIndex(ValueIndex):
    default_field_name = 'mimeType'
    default_interface = ValidatingItemMimeType
    
@interface.implementer(IMetadataCatalog)
class MetadataAssesmentCatalog(Catalog):
    
    super_index_doc = Catalog.index_doc

    def index_doc(self, docid, ob):
        pass

    def force_index_doc(self, docid, ob):
        self.super_index_doc( docid, ob)

def install_assesment_catalog(site_manager_container, intids=None):
    lsm = site_manager_container.getSiteManager()
    if intids is None:
        intids = lsm.getUtility(IIntIds)

    catalog = lsm.queryUtility(IMetadataCatalog, name=CATALOG_NAME)
    if catalog is not None:
        return catalog

    catalog = MetadataAssesmentCatalog(family=intids.family)
    locate(catalog, site_manager_container, CATALOG_NAME)
    intids.register( catalog )
    lsm.registerUtility(catalog, provided=IMetadataCatalog, name=CATALOG_NAME )

    for name, clazz in ( (IX_ITEM_ID, ItemIdIndex), 
                         (IX_CREATOR, CreatorIndex),
                         (IX_COURSE, CatalogEntryIDIndex) 
                         (IX_ITEM_MIME_TYPE, ItemMimeTypeIndex)):
        index = clazz( family=intids.family )
        assert ICatalogIndex.providedBy(index)
        intids.register( index )
        locate(index, catalog, name)
        catalog[name] = index
    return catalog
