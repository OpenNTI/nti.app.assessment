#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from datetime import datetime

import os
from six.moves.urllib_parse import urlparse

from html5lib import HTMLParser
from html5lib import treebuilders

from ordered_set import OrderedSet

from zope import component
from zope import interface
from zope import lifecycleevent

from zope.component.hooks import getSite

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from persistent.list import PersistentList

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.history import has_savepoints

from nti.app.assessment.common.evaluations import get_containers_for_evaluation_object
from nti.app.assessment.common.evaluations import get_evaluation_containment

from nti.app.assessment.common.hostpolicy import get_resource_site_registry

from nti.app.assessment.common.submissions import has_submissions
from nti.app.assessment.common.submissions import has_inquiry_submissions

from nti.app.assessment.interfaces import IQEvaluations

from nti.app.base.abstract_views import get_source_filer
from nti.app.base.abstract_views import get_safe_source_filename

from nti.app.contentfolder import ASSETS_FOLDER
from nti.app.contentfolder import IMAGES_FOLDER
from nti.app.contentfolder import DOCUMENTS_FOLDER

from nti.app.contentfolder.resources import is_internal_file_link
from nti.app.contentfolder.resources import get_file_from_external_link

from nti.app.externalization.error import raise_json_error

from nti.app.products.courseware.resources.filer import is_image

from nti.assessment import EVALUATION_INTERFACES

from nti.assessment.common import interface_of_assessment

from nti.assessment.interfaces import IQHint
from nti.assessment.interfaces import IQPart
from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQAssignmentPart
from nti.assessment.interfaces import IQEvaluationItemContainer
from nti.assessment.interfaces import IQNonGradableFillInTheBlankWithWordBankPart
from nti.assessment.interfaces import IQEditableEvaluation

from nti.contentfile.interfaces import IContentBaseFile

from nti.contentfragments.html import _html5lib_tostring

from nti.contentfragments.interfaces import IHTMLContentFragment

from nti.contenttypes.courses.discussions.interfaces import ICourseDiscussions

from nti.contenttypes.courses.discussions.utils import get_topic_key

from nti.contenttypes.courses.interfaces import NTI_COURSE_FILE_SCHEME

from nti.contenttypes.courses.utils import get_parent_course

from nti.coremetadata.interfaces import IDeletedObjectPlaceholder

from nti.externalization import to_external_object

from nti.externalization.interfaces import StandardExternalFields

from nti.links import Link

from nti.publishing.interfaces import IPublishable

from nti.site.interfaces import IHostPolicyFolder

from nti.site.utils import registerUtility
from nti.site.utils import unregisterUtility

logger = __import__('logging').getLogger(__name__)

CLASS = StandardExternalFields.CLASS
LINKS = StandardExternalFields.LINKS
MIME_TYPE = StandardExternalFields.MIMETYPE


def indexed_iter():
    return PersistentList()


def associate(model, source):
    if IContentBaseFile.providedBy(source):
        source.add_association(model)
        lifecycleevent.modified(source)


def get_html_content_fields(context):
    result = []
    if IQHint.providedBy(context):
        result.append((context, 'value'))
    elif IQPart.providedBy(context):
        result.append((context, 'content'))
        result.append((context, 'explanation'))
        for hint in context.hints or ():
            result.extend(get_html_content_fields(hint))
        if IQNonGradableFillInTheBlankWithWordBankPart.providedBy(context):
            result.append((context, 'input'))
    elif   IQAssignment.providedBy(context) \
        or IQuestion.providedBy(context) \
        or IQPoll.providedBy(context):
        result.append((context, 'content'))
        for part in context.parts or ():
            result.extend(get_html_content_fields(part))
    elif IQuestionSet.providedBy(context) or IQSurvey.providedBy(context):
        for question in context.questions or ():
            result.extend(get_html_content_fields(question))
    elif IQAssignmentPart.providedBy(context):
        result.append((context, 'content'))
        result.extend(get_html_content_fields(context.question_set))
    elif IQAssignment.providedBy(context):
        result.append((context, 'content'))
        for parts in context.parts or ():
            result.extend(get_html_content_fields(parts))
    return result


def import_evaluation_content(model, context=None, user=None, sources=None,
                              source_filer=None, target_filer=None):
    if source_filer is None:
        source_filer = get_source_filer(context, user)
    if target_filer is None:
        target_filer = source_filer
    sources = sources if sources is not None else {}
    for obj, name in get_html_content_fields(model):
        name = str(name)
        value = getattr(obj, name, None)
        if value and source_filer != None:
            modified = False
            value = IHTMLContentFragment(value)
            if not value:
                continue
            __traceback_info__ = value,
            parser = HTMLParser(tree=treebuilders.getTreeBuilder("lxml"),
                                namespaceHTMLElements=False)
            doc = parser.parse(value)
            for e in doc.iter():
                attrib = e.attrib
                href = attrib.get('href')
                if not href:
                    continue
                elif is_internal_file_link(href):
                    source = get_file_from_external_link(href)
                    associate(model, source)
                elif href.startswith(NTI_COURSE_FILE_SCHEME):
                    save_in_filer = True
                    path = urlparse(href).path
                    path, name = os.path.split(path)
                    source = sources.get(name)
                    if source is None:
                        source = source_filer.get(name, path)
                        if source is not None:
                            associate(model, source)
                            location = source_filer.get_external_link(source)
                            save_in_filer = target_filer is not source_filer
                        else:
                            logger.error("Missing source %s", href)
                            continue
                    if source is not None and save_in_filer and target_filer is not None:
                        structure = bool(not path)
                        key = get_safe_source_filename(source, name)
                        location = target_filer.save(key, source, overwrite=False,
                                                     structure=structure,
                                                     bucket=path, context=model)
                    # change href
                    attrib['href'] = location
                    modified = True

            if modified:
                value = _html5lib_tostring(doc, sanitize=False)
                setattr(obj, name, value)
    return model


def export_evaluation_content(model, target_filer):
    for obj, name in get_html_content_fields(model):
        value = getattr(obj, name, None)
        if not value:
            continue
        modified = False
        value = IHTMLContentFragment(value)
        parser = HTMLParser(tree=treebuilders.getTreeBuilder("lxml"),
                            namespaceHTMLElements=False)
        doc = parser.parse(value)
        for e in doc.iter():
            attrib = e.attrib
            href = attrib.get('href')
            if not href:
                continue
            elif is_internal_file_link(href):
                resource = get_file_from_external_link(href)
                rsrc_name = resource.name
                contentType = resource.contentType

                if hasattr(resource, 'path'):
                    path = resource.path
                    path = os.path.split(path)[0]  # remove resource name
                    path = path[1:] if path.startswith('/') else path
                elif is_image(rsrc_name, contentType):
                    path = IMAGES_FOLDER
                else:
                    path = DOCUMENTS_FOLDER
                if      not path.startswith(IMAGES_FOLDER) \
                    and not path.startswith(DOCUMENTS_FOLDER):
                    # under assets folder
                    path = os.path.join(ASSETS_FOLDER, path)
                # save resource
                target_filer.save(resource.name,
                                  resource,
                                  bucket=path,
                                  context=obj,
                                  overwrite=True,
                                  contentType=contentType)
                # get course file scheme
                internal = NTI_COURSE_FILE_SCHEME + path + "/" + resource.name
                attrib['href'] = internal
                modified = True

        if modified:
            value = _html5lib_tostring(doc, sanitize=False)
            setattr(obj, name, value)
    return model


def register_context(context, force=False, registry=None):
    ntiid = context.ntiid
    provided = interface_of_assessment(context)
    if registry is None:
        registry = get_resource_site_registry(context)
    if registry.queryUtility(provided, name=ntiid) is None:
        registerUtility(registry, context, provided, name=ntiid)
    elif force:  # [re]register new object
        unregisterUtility(registry, provided=provided, name=ntiid)
        registerUtility(registry, context, provided, name=ntiid)
    # process 'children'
    if IQEvaluationItemContainer.providedBy(context):
        for item in context.Items or ():
            register_context(item, registry=registry)
    elif IQAssignment.providedBy(context):
        for item in context.iter_question_sets():
            register_context(item, registry=registry)


def validate_submissions(theObject, course, request=None, allow_force=False):
    if IQInquiry.providedBy(theObject):
        result = has_inquiry_submissions(theObject, course)
    else:
        result = has_submissions(theObject, course)
    if result:
        request = request or get_current_request()

        message = _(u"Evaluation has submissions.")
        code = 'ObjectHasSubmissions'
        if allow_force:
            raise_destructive_challenge(code, message, request)
        else:
            raise_json_error(request,
                             hexc.HTTPUnprocessableEntity,
                             {
                                 'message': message,
                                 'code': code,
                             },
                             None)


def raise_destructive_challenge(code, message, request=None, force_flag_name="force"):
    request = request or get_current_request()
    params = dict(request.params)
    params[force_flag_name] = True
    links = (
        Link(request.path, rel='confirm',
             params=params, method='PUT'),
    )
    raise_json_error(request,
                     hexc.HTTPConflict,
                     {
                         CLASS: 'DestructiveChallenge',
                         'message': message,
                         'code': code,
                         LINKS: to_external_object(links),
                         MIME_TYPE: 'application/vnd.nextthought.destructivechallenge'
                     },
                     None)


def validate_savepoints(theObject, course, request=None):
    if has_savepoints(theObject, course):
        request = request or get_current_request()
        raise_json_error(request,
                         hexc.HTTPUnprocessableEntity,
                         {
                             'message': _(u"Evaluation has savepoints."),
                             'code': 'ObjectHasSavepoints',
                         },
                         None)


def validate_published(theObject, unused_course=None, request=None):
    if IPublishable.providedBy(theObject) and theObject.isPublished():
        request = request or get_current_request()
        raise_json_error(request,
                         hexc.HTTPUnprocessableEntity,
                         {
                             'message': _(u"Evaluation has been published."),
                             'code': 'ObjectIsPublished',
                         },
                         None)


def validate_structural_edits(theObject, course, request=None, allow_force=False):
    """
    Validate that we can structurally edit the given evaluation object.
    We can as long as there are no savepoints or submissions.
    """
    assignments = get_containers_for_evaluation_object(theObject)
    for assignment in assignments:
        validate_savepoints(assignment, course, request)
    validate_submissions(theObject, course, request, allow_force=allow_force)


def delete_evaluation(evaluation):
    """
    Delete the specified editable evaluation
    """
    # Clean up question sets under assignments
    if IQAssignment.providedBy(evaluation):
        for part in evaluation.parts or ():
            if part.question_set is not None:
                delete_evaluation(part.question_set)

    # delete from evaluations .. see adapters/model
    context = None
    try:
        context = evaluation.__parent__.__parent__
        evaluations = IQEvaluations(context, None)
        if evaluations and evaluation.ntiid in evaluations:
            del evaluations[evaluation.ntiid]
    except AttributeError:
        pass
    evaluation.__home__ = None

    # remove from registry
    provided = interface_of_assessment(evaluation)
    registered = component.queryUtility(provided,
                                        name=evaluation.ntiid)
    if registered is not None:
        site = IHostPolicyFolder(context, getSite())
        registry = site.getSiteManager()
        unregisterUtility(registry,
                          provided=provided,
                          name=evaluation.ntiid)


def course_discussions(course, by_topic_key=True):
    result = {}
    courses = OrderedSet((course, get_parent_course(course)))
    for course in courses:
        discussions = ICourseDiscussions(course)
        for discussion in discussions.values():
            if by_topic_key:
                key = get_topic_key(discussion)
            else:
                key = discussion.id
            if key not in result:
                result[key] = discussion
    return result


EVALUATION_SORT_ORDER = {
    i: x for i, x in enumerate(EVALUATION_INTERFACES)
}.items()


def sort_evaluation_key(item):
    for i, iface in EVALUATION_SORT_ORDER:
        if iface.providedBy(item):
            return i
    return 0


def re_register_assessment_object(context, old_iface, new_iface):
    """
    Unregister the assessment context under the given old interface and register
    under the given new interface.
    """
    ntiid = context.ntiid
    folder = IHostPolicyFolder(context)
    registry = folder.getSiteManager()
    registerUtility(registry, context, provided=new_iface,
                    name=ntiid, event=False)
    unregisterUtility(registry, provided=old_iface, name=ntiid)
    # Make sure we re-index.
    lifecycleevent.modified(context)


def is_inquiry_closed(evaluation, begin_date, end_date):
    now = datetime.utcnow()

    if begin_date is not None and now < begin_date:
        is_closed = True
    elif end_date is not None and now > end_date:
        is_closed = True
    else:
        is_closed = evaluation.isClosed

    return is_closed
