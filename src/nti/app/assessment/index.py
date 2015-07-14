#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.intid import IIntIds

from zope.location import locate

from zope.catalog.interfaces import ICatalogIndex

from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission

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

CATALOG_NAME = 'nti.dataserver.++etc++assesment-catalog'

IX_ENTRY = IX_COURSE = 'course'
IX_ASSESSMENT_ID = 'assesmentId'
IX_ASSESSMENT_TYPE = 'assesmentType'
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
			assesment = iface(obj, None)
			if assesment is not None:
				course = ICourseInstance(assesment, None)  # course is lineage
				entry = ICourseCatalogEntry(course, None)  # entry is an annotation
				return entry
		return None

	def __init__(self, obj, default=None):
		entry = self._entry(obj)
		if entry is not None:
			self.ntiid = unicode(entry.ntiid)

	def __reduce__(self):
		raise TypeError()

class CatalogEntryIDIndex(ValueIndex):
	default_field_name = 'ntiid'
	default_interface = ValidatingCatalogEntryID

class ValidatingAssesmentID(object):

	__slots__ = (b'assesmentId',)

	def __init__(self, obj, default=None):
		if  IUsersCourseAssignmentHistoryItem.providedBy(obj) or \
			IUsersCourseInquiryItem.providedBy(obj):
			self.assesmentId = obj.__name__

	def __reduce__(self):
		raise TypeError()

class AssesmentIdIndex(ValueIndex):
	default_field_name = 'assesmentId'
	default_interface = ValidatingAssesmentID

class ValidatingAssesmentType(object):

	__slots__ = (b'type',)

	def __init__(self, obj, default=None):
		try:
			if IUsersCourseAssignmentHistoryItem.providedBy(obj):
				self.type = 'Assignment'
			elif IUsersCourseInquiryItem.providedBy(obj):
				if IQSurveySubmission.providedBy(obj.Submission):
					self.type = 'Survey'
				elif IQPollSubmission.providedBy(obj.Submission):
					self.type = 'Poll'
		except (AttributeError, TypeError):
			pass

	def __reduce__(self):
		raise TypeError()

class AssesmentTypeIndex(ValueIndex):
	default_field_name = 'type'
	default_interface = ValidatingAssesmentType

@interface.implementer(IMetadataCatalog)
class MetadataAssesmentCatalog(Catalog):

	super_index_doc = Catalog.index_doc

	def index_doc(self, docid, ob):
		pass

	def force_index_doc(self, docid, ob):
		self.super_index_doc(docid, ob)

def install_assesment_catalog(site_manager_container, intids=None):
	lsm = site_manager_container.getSiteManager()
	if intids is None:
		intids = lsm.getUtility(IIntIds)

	catalog = lsm.queryUtility(IMetadataCatalog, name=CATALOG_NAME)
	if catalog is not None:
		return catalog

	catalog = MetadataAssesmentCatalog(family=intids.family)
	locate(catalog, site_manager_container, CATALOG_NAME)
	intids.register(catalog)
	lsm.registerUtility(catalog, provided=IMetadataCatalog, name=CATALOG_NAME)

	for name, clazz in ((IX_CREATOR, CreatorIndex),
						(IX_COURSE, CatalogEntryIDIndex),
						(IX_ASSESSMENT_ID, AssesmentIdIndex),
						(IX_ASSESSMENT_TYPE, AssesmentTypeIndex)):
		index = clazz(family=intids.family)
		assert ICatalogIndex.providedBy(index)
		intids.register(index)
		locate(index, catalog, name)
		catalog[name] = index
	return catalog
