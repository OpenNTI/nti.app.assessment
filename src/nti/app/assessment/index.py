#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import interface

from zope.deprecation import deprecated

from zope.intid.interfaces import IIntIds

from zope.location import locate

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver.interfaces import ICreatedUsername
from nti.dataserver.interfaces import IMetadataCatalog

from nti.site.interfaces import IHostPolicyFolder

from nti.traversal.traversal import find_interface

from nti.zope_catalog.catalog import Catalog

from nti.zope_catalog.index import NormalizationWrapper
from nti.zope_catalog.index import IntegerAttributeIndex
from nti.zope_catalog.index import ValueIndex as RawValueIndex
from nti.zope_catalog.index import AttributeValueIndex as ValueIndex

from nti.zope_catalog.string import StringTokenNormalizer

CATALOG_NAME = 'nti.dataserver.++etc++assesment-catalog'

IX_SITE = 'site'
IX_ENTRY = IX_COURSE = 'course'
IX_ASSESSMENT_ID = 'assesmentId'
IX_ASSESSMENT_TYPE = 'assesmentType'
IX_CREATOR = IX_STUDENT = IX_USERNAME = 'creator'

class ValidatingSite(object):

	__slots__ = (b'site',)

	@classmethod
	def _folder(cls, obj):
		for iface in (IUsersCourseInquiryItem, IUsersCourseAssignmentHistoryItem):
			item = iface(obj, None)
			if item is not None:
				course = ICourseInstance(item, None)  # course is lineage
				folder = find_interface(course, 
										IHostPolicyFolder, 
										strict=False) if course is not None else None
				return folder
		return None
	
	def __init__(self, obj, default=None):
		folder = self._folder(obj)
		if folder is not None:
			self.site = unicode(folder.__name__)

	def __reduce__(self):
		raise TypeError()

class SiteIndex(ValueIndex):
	default_field_name = 'site'
	default_interface = ValidatingSite

class ValidatingCatalogEntryID(object):

	__slots__ = (b'ntiid',)

	@classmethod
	def _entry(cls, obj):
		for iface in (IUsersCourseInquiryItem, IUsersCourseAssignmentHistoryItem):
			item = iface(obj, None)
			if item is not None:
				course = ICourseInstance(item, None)  # course is lineage
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

class CreatorRawIndex(RawValueIndex):
	pass

def CreatorIndex(family=None):
	return NormalizationWrapper(field_name='creator_username',
								interface=ICreatedUsername,
								index=CreatorRawIndex(family=family),
								normalizer=StringTokenNormalizer())

class ValidatingAssesmentID(object):

	__slots__ = (b'assesmentId',)

	def __init__(self, obj, default=None):
		if  IUsersCourseAssignmentHistoryItem.providedBy(obj) or \
			IUsersCourseInquiryItem.providedBy(obj):
			self.assesmentId = obj.__name__  # by definition

	def __reduce__(self):
		raise TypeError()

class AssesmentIdIndex(ValueIndex):
	default_field_name = 'assesmentId'
	default_interface = ValidatingAssesmentID

def get_assesment_type(obj):
	result = None
	try:
		if IUsersCourseAssignmentHistoryItem.providedBy(obj):
			result = u'Assignment'
		elif IUsersCourseInquiryItem.providedBy(obj):
			if IQSurveySubmission.providedBy(obj.Submission):
				result = u'Survey'
			elif IQPollSubmission.providedBy(obj.Submission):
				result = u'Poll'
		elif IQAssignment.providedBy(obj):
			result = u'Assignment'
		elif IQPoll.providedBy(obj):
			result = u'Poll'
		elif IQSurvey.providedBy(obj):
			result = u'Survey'
	except (AttributeError, TypeError):
		pass
	return result

class ValidatingAssesmentType(object):

	__slots__ = (b'type',)

	def __init__(self, obj, default=None):
		self.type = get_assesment_type(obj)

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
	intids = lsm.getUtility(IIntIds) if intids is None else intids
	catalog = lsm.queryUtility(IMetadataCatalog, name=CATALOG_NAME)
	if catalog is not None:
		return catalog

	catalog = MetadataAssesmentCatalog(family=intids.family)
	locate(catalog, site_manager_container, CATALOG_NAME)
	intids.register(catalog)
	lsm.registerUtility(catalog, provided=IMetadataCatalog, name=CATALOG_NAME)

	for name, clazz in ((IX_SITE, SiteIndex),
						(IX_CREATOR, CreatorIndex),
						(IX_COURSE, CatalogEntryIDIndex),
						(IX_ASSESSMENT_ID, AssesmentIdIndex),
						(IX_ASSESSMENT_TYPE, AssesmentTypeIndex)):
		index = clazz(family=intids.family)
		intids.register(index)
		locate(index, catalog, name)
		catalog[name] = index
	return catalog

deprecated('ValidatingCourseIntID', 'No longer used')
class ValidatingCourseIntID(object):
	pass

deprecated('CourseIntIDIndex', 'No longer used')
class CourseIntIDIndex(IntegerAttributeIndex):
	pass
