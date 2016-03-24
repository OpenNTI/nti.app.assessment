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

from nti.app.assessment.utils import copy_assignment

from nti.app.base.abstract_views import AbstractAuthenticatedView

from nti.app.contentlibrary.utils import PAGE_INFO_MT
from nti.app.contentlibrary.utils import PAGE_INFO_MT_JSON
from nti.app.contentlibrary.utils import find_page_info_view_helper

from nti.app.products.courseware.interfaces import ICourseInstanceEnrollment

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignment

from nti.common.property import Lazy
from nti.common.proxy import removeAllProxies

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry
from nti.contenttypes.courses.interfaces import ICourseAssignmentCatalog
from nti.contenttypes.courses.interfaces import ICourseOutlineContentNode
from nti.contenttypes.courses.interfaces import ICourseAssessmentItemCatalog
from nti.contenttypes.courses.interfaces import get_course_assessment_predicate_for_user

from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.contenttypes.presentation.interfaces import INTIAssignmentRef
from nti.contenttypes.presentation.interfaces import INTIQuestionSetRef
from nti.contenttypes.presentation.interfaces import INTILessonOverview

from nti.dataserver import authorization as nauth

from nti.externalization.interfaces import LocatedExternalDict
from nti.externalization.interfaces import StandardExternalFields

ITEMS = StandardExternalFields.ITEMS

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
	def is_ipad_legacy(self):
		result = False
		ua = self.request.environ.get('HTTP_USER_AGENT', '')
		if ua:
			for bua in self._LEGACY_UAS:
				if ua.startswith(bua):
					result = True
					break
		return result

@view_config(context=ICourseInstance)
@view_config(context=ICourseInstanceEnrollment)
@view_defaults(route_name='objects.generic.traversal',
			   renderer='rest',
			   permission=nauth.ACT_READ,
			   request_method='GET',
			   name='AssignmentsByOutlineNode')  # See decorators
class AssignmentsByOutlineNodeDecorator(AssignmentsByOutlineNodeMixin):
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

	@Lazy
	def is_course_instructor(self):
		instance = ICourseInstance(self.context)
		return is_course_instructor_or_editor(instance, self.remoteUser)

	@Lazy
	def _is_editor(self):
		instance = ICourseInstance(self.context)
		return has_permission( nauth.ACT_CONTENT_EDIT, instance )

	def _do_outline(self, instance, items, outline):
		# reverse question set map
		# this is done in case question set refs
		# appear in a lesson overview
		reverse_qset = {}
		for assgs in items.values():
			for asg in assgs:
				for part in asg.parts:
					reverse_qset[part.question_set.ntiid] = asg.ntiid

		def _recur(node):
			if ICourseOutlineContentNode.providedBy(node) and node.ContentNTIID:
				key = node.ContentNTIID
				assgs = items.get(key)
				if assgs:
					outline[key] = [x.ntiid for x in assgs]
				name = node.LessonOverviewNTIID
				lesson = component.queryUtility(INTILessonOverview, name=name or u'')
				for group in lesson or ():
					for item in group:
						if INTIAssignmentRef.providedBy(item):
							outline.setdefault(key, [])
							outline[key].append(item.target or item.ntiid)
						elif INTIQuestionSetRef.providedBy(item):
							ntiid = reverse_qset.get(item.target)
							if ntiid:
								outline.setdefault(key, [])
								outline[key].append(item.target or item.ntiid)
			for child in node.values():
				_recur(child)
		_recur(instance.Outline)
		return outline

	def _do_catalog(self, instance, result):
		catalog = ICourseAssignmentCatalog(instance)
		uber_filter = get_course_assessment_predicate_for_user(self.remoteUser, instance)
		for asg in (x for x in catalog.iter_assignments() if uber_filter(x) or self._is_editor):
			# The assignment's __parent__ is always the 'home' content unit
			parent = asg.__parent__
			if parent is not None:
				if 		not self.is_ipad_legacy \
					and (self.is_course_instructor or self._is_editor):
					asg = copy_assignment(asg, True)
				if ICourseInstance.providedBy(parent):
					parent = ICourseCatalogEntry(parent)
				result.setdefault(parent.ntiid, []).append(asg)
			else:
				logger.error("%s is an assignment without parent unit", asg.ntiid)
		return result

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		instance = ICourseInstance(self.request.context)
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
class NonAssignmentsByOutlineNodeDecorator(AssignmentsByOutlineNodeMixin):
	"""
	For course instances (and things that can be adapted to them),
	there is a view at ``/.../NonAssignmentAssessmentItemsByOutlineNode``. For
	authenticated users, it returns a map from NTIID to the assessment items
	contained within that NTIID.

	At this time, nodes in the course outline
	do not have their own identity as NTIIDs; therefore, the NTIIDs
	returned from here are the NTIIDs of content pages that show up
	in the individual lessons; for maximum granularity, these are returned
	at the lowest level, so a client may need to walk \"up\" the tree
	to identify the corresponding level it wishes to display.
	"""

	@Lazy
	def is_course_instructor(self):
		return is_course_instructor_or_editor(self.context, self.remoteUser)

	def _do_catalog(self, instance, result):
		# Not only must we filter out assignments, we must filter out
		# the question sets that they refer to if they are not allowed
		# by the filter; we assume such sets are only used by the
		# assignment.

		qsids_to_strip = set()
		data = defaultdict(dict)
		catalog = ICourseAssessmentItemCatalog(instance)
		for item in catalog.iter_assessment_items():
			if IQAssignment.providedBy(item):
				for assignment_part in item.parts or ():
					question_set = assignment_part.question_set
					qsids_to_strip.add(question_set.ntiid)
					qsids_to_strip.update(q.ntiid for q in question_set.questions)
			elif IQSurvey.providedBy(item):
				qsids_to_strip.update(p.ntiid for p in item.questions or ())
			else:
				# The item's __parent__ is always the 'home' content unit
				unit = item.__parent__
				if unit is not None:
					# CS: We can remove proxies since the items are neither assignments
					# nor survey, so no course lookup is necesary
					item = removeAllProxies(item)
					data[unit.ntiid][item.ntiid] = item
				else:
					logger.error("%s is an item without parent unit", item.ntiid)

		# Now remove the forbidden
		for ntiid, items in data.items():
			result[ntiid] = [items[x] for x in items.keys() if x not in qsids_to_strip]

		return result

	def __call__(self):
		result = LocatedExternalDict()
		result.__name__ = self.request.view_name
		result.__parent__ = self.request.context

		instance = ICourseInstance(self.request.context)
		if self.is_ipad_legacy:
			self._do_catalog(instance, result)
		else:
			items = result[ITEMS] = {}
			self._do_catalog(instance, items)
		return result
