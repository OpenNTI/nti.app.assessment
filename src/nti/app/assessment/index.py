#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from zope import component
from zope import interface

from zope.deprecation import deprecated

from zope.intid.interfaces import IIntIds

from zope.location import locate

import BTrees

from nti.app.assessment.interfaces import IUsersCourseInquiryItem
from nti.app.assessment.interfaces import IUsersCourseSubmissionItem
from nti.app.assessment.interfaces import IUsersCourseAssignmentHistoryItem

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQPollSubmission
from nti.assessment.interfaces import IQSurveySubmission
from nti.assessment.interfaces import IQEditableEvaluation
from nti.assessment.interfaces import IQAssignmentSubmission

from nti.base._compat import unicode_

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.dataserver.interfaces import IMetadataCatalog

from nti.site.interfaces import IHostPolicyFolder

from nti.traversal.traversal import find_interface

from nti.zope_catalog.catalog import Catalog

from nti.zope_catalog.index import AttributeSetIndex
from nti.zope_catalog.index import NormalizationWrapper
from nti.zope_catalog.index import AttributeKeywordIndex
from nti.zope_catalog.index import IntegerAttributeIndex
from nti.zope_catalog.index import ValueIndex as RawValueIndex
from nti.zope_catalog.index import AttributeValueIndex as ValueIndex

from nti.zope_catalog.string import StringTokenNormalizer


class ExtenedAttributeSetIndex(AttributeSetIndex):

    def remove(self, doc_id, containers):
        """
        remove the specified containers from the doc_id
        """
        old = set(self.documents_to_values.get(doc_id) or ())
        if not old:
            return
        for v in to_iterable(containers):
            old.discard(v)
        if old:
            # call zc.catalog.index.SetIndex which does the actual
            # value indexation
            ZC_SetIndex.index_doc(self, doc_id, old)
        else:
            super(ExtenedAttributeSetIndex, self).unindex_doc(doc_id)


# Submission / Assesed catalog

# Not a very good name
SUBMISSION_CATALOG_NAME = 'nti.dataserver.++etc++assesment-catalog'

IX_SITE = 'site'
IX_COURSE = 'course'
IX_ENTRY = IX_COURSE
IX_SUBMITTED = 'submitted'
IX_ASSESSMENT_ID = 'assesmentId'
IX_ASSESSMENT_TYPE = 'assesmentType'
IX_CREATOR = IX_STUDENT = IX_USERNAME = 'creator'


deprecated('ValidatingCourseIntID',  'No longer used')
class ValidatingCourseIntID(object):
    pass


deprecated('CourseIntIDIndex', 'No longer used')
class CourseIntIDIndex(IntegerAttributeIndex):
    pass


class ValidatingSite(object):

    __slots__ = (b'site',)

    @classmethod
    def _folder(cls, obj):
        item = IUsersCourseSubmissionItem(obj, None)
        if item is not None:
            course = ICourseInstance(item, None)  # course is lineage
            folder = find_interface(course, IHostPolicyFolder, strict=False)
            return folder
        return None

    def __init__(self, obj, default=None):
        folder = self._folder(obj)
        if folder is not None:
            self.site = unicode_(folder.__name__)

    def __reduce__(self):
        raise TypeError()


class SiteIndex(ValueIndex):
    default_field_name = 'site'
    default_interface = ValidatingSite


class ValidatingCatalogEntryID(object):

    __slots__ = (b'ntiid',)

    @classmethod
    def _entry(cls, obj):
        item = IUsersCourseSubmissionItem(obj, None)
        if item is not None:
            course = ICourseInstance(item, None)  # course is lineage
            # entry is an annotation
            entry = ICourseCatalogEntry(course, None)
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
                                interface=IUsersCourseSubmissionItem,
                                index=CreatorRawIndex(family=family),
                                normalizer=StringTokenNormalizer())


class ValidatingAssesmentID(object):

    __slots__ = (b'assesmentId',)

    def __init__(self, obj, default=None):
        if IUsersCourseSubmissionItem.providedBy(obj):
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
        elif IQuestionSet.providedBy(obj):
            result = u'QuestionSet'
        elif IQuestion.providedBy(obj):
            result = u'Question'
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


class ValidatingAssesmentSubmittedType(object):

    __slots__ = (b'submitted',)

    @classmethod
    def get_submitted(cls, item):
        result = set()
        submission = item.Submission
        if IQAssignmentSubmission.providedBy(submission):
            result.add(submission.assignmentId)
            for part in submission.parts or ():
                result.add(part.questionSetId)
                result.update(q.questionId for q in part.questions or ())
        elif IQSurveySubmission.providedBy(submission):
            result.add(submission.surveyId)
            result.update(p.pollId for p in submission.questions or ())
        elif IQPollSubmission.providedBy(submission):
            result.add(submission.pollId)
        result.discard(None)
        return result

    def __init__(self, obj, default=None):
        if     IUsersCourseAssignmentHistoryItem.providedBy(obj) \
            or IUsersCourseInquiryItem.providedBy(obj):
            self.submitted = self.get_submitted(obj)

    def __reduce__(self):
        raise TypeError()


class AssesmentSubmittedIndex(ExtenedAttributeSetIndex):
    default_field_name = 'submitted'
    default_interface = ValidatingAssesmentSubmittedType


@interface.implementer(IMetadataCatalog)
class MetadataAssesmentCatalog(Catalog):

    family = BTrees.family64

    super_index_doc = Catalog.index_doc

    def index_doc(self, docid, ob):
        pass

    def force_index_doc(self, docid, ob):
        self.super_index_doc(docid, ob)


def install_submission_catalog(site_manager_container, intids=None):
    lsm = site_manager_container.getSiteManager()
    intids = lsm.getUtility(IIntIds) if intids is None else intids
    catalog = lsm.queryUtility(IMetadataCatalog, name=SUBMISSION_CATALOG_NAME)
    if catalog is not None:
        return catalog

    catalog = MetadataAssesmentCatalog(family=intids.family)
    locate(catalog, site_manager_container, SUBMISSION_CATALOG_NAME)
    intids.register(catalog)
    lsm.registerUtility(catalog,
                        provided=IMetadataCatalog,
                        name=SUBMISSION_CATALOG_NAME)

    for name, clazz in ((IX_SITE, SiteIndex),
                        (IX_CREATOR, CreatorIndex),
                        (IX_COURSE, CatalogEntryIDIndex),
                        (IX_ASSESSMENT_ID, AssesmentIdIndex),
                        (IX_SUBMITTED, AssesmentSubmittedIndex),
                        (IX_ASSESSMENT_TYPE, AssesmentTypeIndex)):
        index = clazz(family=intids.family)
        intids.register(index)
        locate(index, catalog, name)
        catalog[name] = index
    return catalog


# Evaluation / Containment catalog


EVALUATION_CATALOG_NAME = 'nti.dataserver.++etc++evaluation-catalog'

IX_NTIID = 'ntiid'
IX_EDITABLE = 'editable'
IX_MIMETYPE = 'mimeType'
IX_KEYWORDS = 'keyworkds'
IX_CONTAINERS = 'containers'
IX_CONTAINMENT = 'containment'

from six import integer_types

from zope.catalog.interfaces import ICatalog

from zc.catalog.index import SetIndex as ZC_SetIndex

from pyramid.location import lineage

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.utils import get_courses_for_packages

from nti.externalization.proxy import removeAllProxies


def to_iterable(value):
    if isinstance(value, (list, tuple, set)):
        result = value
    else:
        result = (value,) if value is not None else ()
    return result


def get_uid(item, intids=None):
    if not isinstance(item, integer_types):
        item = removeAllProxies(item)
        intids = component.getUtility(IIntIds) if intids is None else intids
        result = intids.queryId(item)
    else:
        result = item
    return result


class ValidatingEvaluationSite(object):

    __slots__ = (b'site',)

    def __init__(self, obj, default=None):
        if IQEvaluation.providedBy(obj):
            folder = find_interface(obj, IHostPolicyFolder, strict=False)
            if folder is not None:
                self.site = unicode_(folder.__name__)

    def __reduce__(self):
        raise TypeError()


class EvaluationSiteIndex(ValueIndex):
    default_field_name = 'site'
    default_interface = ValidatingEvaluationSite


class ValidatingMimeType(object):

    __slots__ = (b'mimeType',)

    def __init__(self, obj, default=None):
        if IQEvaluation.providedBy(obj):
            self.mimeType = obj.mimeType

    def __reduce__(self):
        raise TypeError()


class EvaluationMimeTypeIndex(ValueIndex):
    default_field_name = 'mimeType'
    default_interface = ValidatingMimeType


class ValidatingEvaluationNTIID(object):

    __slots__ = (b'ntiid',)

    def __init__(self, obj, default=None):
        if IQEvaluation.providedBy(obj):
            self.ntiid = obj.ntiid

    def __reduce__(self):
        raise TypeError()


class EvaluationNTIIDIndex(ValueIndex):
    default_field_name = 'ntiid'
    default_interface = ValidatingEvaluationNTIID


class ValidatingEvaluationContainment(object):

    __slots__ = (b'containment',)

    def _do_survey_question_set(self, obj):
        result = {q.ntiid for q in obj.questions}
        return result

    def _do_assigment_question_set(self, obj):
        result = set()
        for p in obj.parts:
            question_set = p.question_set
            result.add(question_set.ntiid)
            result.update(self._do_survey_question_set(question_set))
        return result

    def __init__(self, obj, default=None):
        if IQSurvey.providedBy(obj) or IQuestionSet.providedBy(obj):
            self.containment = self._do_survey_question_set(obj)
        elif IQAssignment.providedBy(obj):
            self.containment = self._do_assigment_question_set(obj)

    def __reduce__(self):
        raise TypeError()


class EvaluationContainmentIndex(ExtenedAttributeSetIndex):
    default_field_name = 'containment'
    default_interface = ValidatingEvaluationContainment


class ValidatingEvaluationContainers(object):

    __slots__ = (b'containers',)

    def _ntiid_lineage(self, context, test_iface, upper_iface):
        result = set()
        for location in lineage(context):
            if test_iface.providedBy(location):
                result.add(location.ntiid)
            if upper_iface.providedBy(location):
                break
        result.discard(None)
        return result

    def _get_containers(self, obj):
        # content units
        result = self._ntiid_lineage(obj, IContentUnit, IContentPackage)
        # find courses
        folder = find_interface(obj, IHostPolicyFolder, strict=False)
        course = find_interface(obj, ICourseInstance, strict=False)
        if course is not None:
            entry = ICourseCatalogEntry(course, None)
            result.add(getattr(entry, 'ntiid', None))
        elif folder is not None:
            courses = get_courses_for_packages(folder.__name__, result)
            for course in courses:
                entry = ICourseCatalogEntry(course, None)
                result.add(getattr(entry, 'ntiid', None))
        # home
        result.add(getattr(obj.__home__, 'ntiid', None))
        # discard invalid
        result.discard(None)
        return result

    def __init__(self, obj, default=None):
        if IQEvaluation.providedBy(obj):
            self.containers = self._get_containers(obj)

    def __reduce__(self):
        raise TypeError()


class EvaluationContainerIndex(ExtenedAttributeSetIndex):
    default_field_name = 'containers'
    default_interface = ValidatingEvaluationContainers


class ValidatingKeywords(object):

    __slots__ = (b'keywords',)

    def __init__(self, obj, default=None):
        if IQEvaluation.providedBy(obj):
            keywords = set(obj.tags or ())
            if IQAssignment.providedBy(obj) and obj.category_name:
                keywords.add(obj.category_name)
            if keywords:
                self.keywords = sorted(keywords)

    def __reduce__(self):
        raise TypeError()


class EvaluationKeywordIndex(AttributeKeywordIndex):
    default_field_name = 'keywords'
    default_interface = ValidatingKeywords


class ValidatingEditable(object):

    __slots__ = (b'editable',)

    def __init__(self, obj, default=None):
        if IQEvaluation.providedBy(obj):
            self.editable = bool(IQEditableEvaluation.providedBy(obj))

    def __reduce__(self):
        raise TypeError()


class EvaluationEditableIndex(ValueIndex):
    default_field_name = 'editable'
    default_interface = ValidatingEditable


class EvaluationCatalog(Catalog):

    family = BTrees.family64

    @property
    def containment_index(self):
        return self[IX_CONTAINMENT]

    def get_containment(self, item, intids=None):
        doc_id = get_uid(item, intids)
        if doc_id is not None:
            result = self.containment_index.documents_to_values.get(doc_id)
            return set(result or ())
        return set()

    @property
    def containers_index(self):
        return self[IX_CONTAINERS]

    def get_containers(self, item, intids=None):
        doc_id = get_uid(item, intids)
        if doc_id is not None:
            result = self.containers_index.documents_to_values.get(doc_id)
            return set(result or ())
        return set()


def create_evaluation_catalog(catalog=None, family=None):
    catalog = EvaluationCatalog() if catalog is None else catalog
    for name, clazz in ((IX_SITE, EvaluationSiteIndex),
                        (IX_NTIID, EvaluationNTIIDIndex),
                        (IX_KEYWORDS, EvaluationKeywordIndex),
                        (IX_EDITABLE, EvaluationEditableIndex),
                        (IX_MIMETYPE, EvaluationMimeTypeIndex),
                        (IX_CONTAINERS, EvaluationContainerIndex),
                        (IX_CONTAINMENT, EvaluationContainmentIndex),):
        index = clazz(family=family)
        locate(index, catalog, name)
        catalog[name] = index
    return catalog


def install_evaluation_catalog(site_manager_container, intids=None):
    lsm = site_manager_container.getSiteManager()
    intids = lsm.getUtility(IIntIds) if intids is None else intids
    catalog = lsm.queryUtility(ICatalog, name=EVALUATION_CATALOG_NAME)
    if catalog is not None:
        return catalog

    catalog = EvaluationCatalog()
    locate(catalog, site_manager_container, EVALUATION_CATALOG_NAME)
    intids.register(catalog)
    lsm.registerUtility(catalog,
                        provided=ICatalog,
                        name=EVALUATION_CATALOG_NAME)

    catalog = create_evaluation_catalog(catalog=catalog, family=intids.family)
    for index in catalog.values():
        intids.register(index)
    return catalog
