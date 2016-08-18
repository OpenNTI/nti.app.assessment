#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Views related to assessment.

.. $Id$
"""

from __future__ import print_function, unicode_literals, absolute_import, division
__docformat__ = "restructuredtext en"

logger = __import__('logging').getLogger(__name__)

from collections import defaultdict

from zope import component

from pyramid import httpexceptions as hexc

from pyramid.view import view_config
from pyramid.view import view_defaults

from nti.app.assessment import ASSESSMENT_PRACTICE_SUBMISSION

from nti.app.assessment.interfaces import ICourseEvaluations

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentlibrary.utils import PAGE_INFO_MT
from nti.app.contentlibrary.utils import PAGE_INFO_MT_JSON
from nti.app.contentlibrary.utils import find_page_info_view_helper

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.appserver.interfaces import INewObjectTransformer

from nti.appserver.pyramid_authorization import has_permission

from nti.appserver.ugd_edit_views import UGDPostView

from nti.assessment.common import get_containerId

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQAssessment
from nti.assessment.interfaces import IQAssessmentItemContainer

from nti.common.property import Lazy

from nti.contentlibrary.indexed_data import get_library_catalog

from nti.contenttypes.courses.common import get_course_packages

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import ICourseOutlineContentNode
from nti.contenttypes.courses.interfaces import ICourseSelfAssessmentItemCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.presentation.interfaces import INTIAssignmentRef
from nti.contenttypes.presentation.interfaces import INTIQuestionSetRef

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

from nti.externalization.proxy import removeAllProxies

from nti.site.site import get_component_hierarchy_names

from nti.traversal.traversal import find_interface

ITEMS = StandardExternalFields.ITEMS
LAST_MODIFIED = StandardExternalFields.LAST_MODIFIED

# In pyramid 1.4, there is some minor wonkiness with the accept= request predicate.
# Your view can get called even if no Accept header is present if all the defined
# views include a non-matching accept predicate. Still, this is much better than
# the behaviour under 1.3.

_read_view_defaults = dict(route_name='objects.generic.traversal',
							renderer='rest',
							permission=nauth.ACT_READ,
							request_method='GET')
_question_view = dict(context=IQuestion)
_question_view.update(_read_view_defaults)

_question_set_view = dict(context=IQuestionSet)
_question_set_view.update(_read_view_defaults)

_assignment_view = dict(context=IQAssignment)
_assignment_view.update(_read_view_defaults)

_inquiry_view = dict(context=IQInquiry)
_inquiry_view.update(_read_view_defaults)

@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_assignment_view)
@view_config(accept=str(PAGE_INFO_MT_JSON),
			 **_inquiry_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_question_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_question_set_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_inquiry_view)
@view_config(accept=str(PAGE_INFO_MT),
			 **_assignment_view)
def pageinfo_from_question_view(request):
	assert request.accept
	# questions are now generally held within their containing IContentUnit,
	# but some old tests don't parent them correctly, using strings
	content_unit_or_ntiid = request.context.__parent__
	return find_page_info_view_helper(request, content_unit_or_ntiid)

@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_question_view)
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_question_set_view)
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_assignment_view)
@view_config(accept=str('application/vnd.nextthought.link+json'),
			 **_inquiry_view)
def get_question_view_link(request):
	# Not supported.
	return hexc.HTTPBadRequest()

@view_config(accept=str(''),  # explicit empty accept, else we get a ConfigurationConflict
			 ** _question_view)  # and/or no-Accept header goes to the wrong place
@view_config(**_question_view)
@view_config(accept=str(''),
			 **_question_set_view)
@view_config(**_question_set_view)
@view_config(accept=str(''),
			 **_assignment_view)
@view_config(**_assignment_view)
@view_config(accept=str(''),
			 **_inquiry_view)
@view_config(**_inquiry_view)
def get_question_view(request):
	return request.context

del _inquiry_view
del _question_view
del _assignment_view
del _read_view_defaults

class AssignmentsByOutlineNodeMixin(AbstractAuthenticatedView):

	_LEGACY_UAS = (
		"NTIFoundation DataLoader NextThought/1.0",
		"NTIFoundation DataLoader NextThought/1.1.",
		"NTIFoundation DataLoader NextThought/1.2.",
		"NTIFoundation DataLoader NextThought/1.3.",
		"NTIFoundation DataLoader NextThought/1.4.0"
	)

	@Lazy
	def _is_editor(self):
		instance = ICourseInstance(self.context)
		return has_permission(nauth.ACT_CONTENT_EDIT, instance)

	@Lazy
	def is_ipad_legacy(self):
		result = False
		ua = self.request.environ.get('HTTP_USER_AGENT', '')
		if ua:
			for bua in self._LEGACY_UAS:
				if ua.startswith(bua):
					result = True
					break
		return result

	@Lazy
	def _lastModified(self):
		instance = ICourseInstance(self.context)
		result = ICourseEvaluations(instance).lastModified or 0
		for package in get_course_packages(instance):
			result = max(result, IQAssessmentItemContainer(package).lastModified or 0)
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='AssignmentsByOutlineNode')  # See decorators
class AssignmentsByOutlineNodeView(AssignmentsByOutlineNodeMixin):
	"""
	For course instances (and things that can be adapted to them),
	there is a view at ``/.../AssignmentsByOutlineNode``. For
	authenticated users, it returns a map from NTIID to the assignments
	contained within that NTIID.

	At this time, nodes in the course outline
	do not have their own identity as NTIIDs; therefore, the NTIIDs
	returned from here are the NTIIDs of content pages that show up
	in the individual lessons; for maximum granularity, these are returned
	at the lowest level, so a client may need to walk \"up\" the tree
	to identify the corresponding level it wishes to display.
	"""

	def _do_outline(self, instance, items, outline):
		# reverse question set map
		# this is done in case question set refs
		# appear in a lesson overview
		reverse_qset = {}
		for assgs in items.values():
			for asg in assgs:
				for part in asg.parts:
					reverse_qset[part.question_set.ntiid] = asg.ntiid

		# use library catalog to find
		# all assignment and question-set refs
		seen = set()
		catalog = get_library_catalog()
		sites = get_component_hierarchy_names()
		ntiid = ICourseCatalogEntry(instance).ntiid
		provided = (INTIAssignmentRef, INTIQuestionSetRef)
		for obj in catalog.search_objects(provided=provided,
										  container_ntiids=ntiid,
										  sites=sites):
			# find property content node
			node = find_interface(obj, ICourseOutlineContentNode, strict=False)
			if node is None or not node.ContentNTIID:
				continue
			key = node.ContentNTIID

			# start if possible with collected items
			assgs = items.get(key)
			if assgs and key not in seen:
				seen.add(key)
				outline[key] = [x.ntiid for x in assgs]

			# add target to outline key
			if INTIAssignmentRef.providedBy(obj):
				outline.setdefault(key, [])
				outline[key].append(obj.target or obj.ntiid)
			elif INTIQuestionSetRef.providedBy(obj):
				ntiid = reverse_qset.get(obj.target)
				if ntiid:
					outline.setdefault(key, [])
					outline[key].append(ntiid)

		return outline

	def _do_catalog(self, instance, result):
		catalog = ICourseAssignmentCatalog(instance)
		uber_filter = get_course_assessment_predicate_for_user(self.remoteUser, instance)
		# Must grab all assigments in our parent (since they may be referenced in shared lessons.
		assignments = catalog.iter_assignments(course_lineage=True)
		for asg in (x for x in assignments if self._is_editor or uber_filter(x)):
			container_id = get_containerId(asg)
			if container_id:
				result.setdefault(container_id, []).append(asg)
			else:
				logger.error("%s is an assignment without parent container", asg.ntiid)
		return result

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context
		self.request.acl_decoration = self._is_editor

		instance = ICourseInstance(self.request.context)
		result[LAST_MODIFIED] = result.lastModified = self._lastModified

		if self.is_ipad_legacy:
			self._do_catalog(instance, result)
		else:
			items = result[ITEMS] = {}
			outline = result['Outline'] = {}
			self._do_catalog(instance, items)
			self._do_outline(instance, items, outline)
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='NonAssignmentAssessmentItemsByOutlineNode')  # See decorators
class NonAssignmentsByOutlineNodeView(AssignmentsByOutlineNodeMixin):
	"""
	For course instances (and things that can be adapted to them),
	there is a view at ``/.../NonAssignmentAssessmentItemsByOutlineNode``. For
	authenticated users, it returns a map from NTIID to the assessment items
	contained within that NTIID.

	At the time this was created, nodes in the course outline
	do not have their own identity as NTIIDs; therefore, the NTIIDs
	returned from here are the NTIIDs of content pages that show up
	in the individual lessons; for maximum granularity, these are returned
	at the lowest level, so a client may need to walk \"up\" the tree
	to identify the corresponding level it wishes to display.
	"""

	def _do_catalog(self, instance, result):
		qsids_to_strip = set()
		data = defaultdict(dict)
		catalog = ICourseSelfAssessmentItemCatalog(instance)
		for item in catalog.iter_assessment_items(exclude_editable=True):
			# CS: We can remove proxies since the items are neither assignments
			# nor survey, so no course lookup is necesary
			item = removeAllProxies(item)
			container_id = get_containerId(item)
			if container_id:
				data[container_id][item.ntiid] = item
			else:
				logger.error("%s is an item without container", item.ntiid)

		# Now remove the forbidden
		for ntiid, items in data.items():
			result_items = [items[x] for x in items.keys() if x not in qsids_to_strip]
			if result_items:
				result[ntiid] = result_items

		return result

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context
		self.request.acl_decoration = self._is_editor

		instance = ICourseInstance(self.request.context)
		result[LAST_MODIFIED] = result.lastModified = self._lastModified

		if self.is_ipad_legacy:
			self._do_catalog(instance, result)
		else:
			items = result[ITEMS] = {}
			self._do_catalog(instance, items)
		return result

@view_config(route_name="objects.generic.traversal",
			 context=IQuestionSet,
			 renderer='rest',
			 name=ASSESSMENT_PRACTICE_SUBMISSION,
			 request_method='POST')
class SelfAssessmentPracticeSubmissionPostView(UGDPostView):
	"""
	A practice self-assessment submission view that will assess results
	but not persist.
	"""

	def _assess(self, submission):
		transformer = component.queryMultiAdapter((self.request, submission),
												   INewObjectTransformer)
		if transformer is None:
			transformer = component.queryAdapter(submission,
												 INewObjectTransformer)

		assessed = transformer(submission)
		return assessed

	def _do_call(self):
		submission, _ = self.readCreateUpdateContentObject(self.remoteUser,
														   search_owner=True)
		try:
			result = self._assess(submission)
			return result
		finally:
			self.request.environ['nti.commit_veto'] = 'abort'

@view_config(route_name='objects.generic.traversal',
			 renderer='rest',
			 context=IQAssessment,
			 permission=nauth.ACT_READ,
			 request_method='GET',
			 name="schema")
class AssessmentSchemaView(AbstractAuthenticatedView):

	def __call__(self):
		result = self.context.schema()
		return result
