#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import os
import copy

from pyramid.threadlocal import get_current_request

import simplejson

from six.moves import urllib_parse

from zope import component
from zope import interface

from zope.intid.interfaces import IIntIds

from zope.proxy import isProxy

from nti.app.assessment.common.evaluations import proxy
from nti.app.assessment.common.evaluations import AssessmentItemProxy
from nti.app.assessment.common.evaluations import get_course_assignments
from nti.app.assessment.common.evaluations import get_course_from_evaluation

from nti.app.assessment.common.utils import get_user

from nti.app.assessment.interfaces import ACT_DOWNLOAD_GRADES

from nti.app.assessment.interfaces import ISolutionDecorationConfig
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadata
from nti.app.assessment.interfaces import IUsersCourseAssignmentAttemptMetadataItem

from nti.app.authentication import get_remote_user

from nti.appserver.pyramid_authorization import has_permission

from nti.assessment.interfaces import IQPoll
from nti.assessment.interfaces import IQSurvey
from nti.assessment.interfaces import IQuestion
from nti.assessment.interfaces import IQFilePart
from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQuestionSet
from nti.assessment.interfaces import IQEvaluationContainerIdGetter

from nti.assessment.randomized import questionbank_question_chooser

from nti.assessment.randomized.interfaces import IQuestionBank
from nti.assessment.randomized.interfaces import IPrincipalSeedSelector
from nti.assessment.randomized.interfaces import IRandomizedPartGraderUnshuffleValidator

from nti.contentlibrary.interfaces import IContentUnit
from nti.contentlibrary.interfaces import IContentPackage

from nti.contenttypes.courses.interfaces import ICourseInstance
from nti.contenttypes.courses.interfaces import ICourseCatalogEntry

from nti.contenttypes.courses.utils import is_course_instructor_or_editor

from nti.dataserver.authorization import ACT_CONTENT_EDIT

from nti.dataserver.interfaces import IUsernameSubstitutionPolicy

from nti.externalization.proxy import removeAllProxies

from nti.ntiids.ntiids import find_object_with_ntiid

logger = __import__('logging').getLogger(__name__)


_r47694_map = None
def r47694():
    """
    in r47694 we introduced a new type of randomizer based on the sha224 hash
    algorithm, however, we did not take into account the fact that there were
    assignments (i.e. question banks) already taken. This cause incorrect
    questions to be returned. Fortunatelly, there were few student takers,
    so we introduce this patch to force sha224 randomizer for those students/
    assessment pairs. We now use the orginal randomizer for legacy purposes
    """
    # pylint: disable=global-statement
    global _r47694_map
    if _r47694_map is None:
        path = os.path.join(os.path.dirname(__file__), "hacks/r47694.json")
        with open(path, "r") as fp:
            _r47694_map = simplejson.load(fp)
    return _r47694_map


def make_sha224randomized(context):
    iface = getattr(context, 'sha224randomized_interface', None)
    if iface is not None:
        interface.alsoProvides(context, iface)
        return True
    return False


def sublocations(context):
    if hasattr(context, 'sublocations'):
        tuple(context.sublocations())
    return context


def has_question_bank(a):
    if IQAssignment.providedBy(a):
        for part in a.parts or ():
            if IQuestionBank.providedBy(part.question_set):
                return True
    return False


def do_copy(source):
    if isProxy(source, AssessmentItemProxy):
        result = copy.copy(removeAllProxies(source))
        result = proxy(result,
                       source.ContentUnitNTIID,
                       source.CatalogEntryNTIID)
    else:
        result = copy.copy(source)
    return result


def copy_part(part):
    result = do_copy(part)
    return result


def copy_poll(context):
    result = do_copy(context)
    result.parts = [copy_part(p) for p in context.parts]
    sublocations(result)
    return result


def copy_question(q):
    result = do_copy(q)
    result.parts = [copy_part(p) for p in q.parts or ()]
    sublocations(result)
    return result


def copy_survey(survey):
    result = do_copy(survey)
    result.questions = [copy_poll(q) for q in survey.Items]
    sublocations(result)
    return result


def copy_questionset(qs):
    result = do_copy(qs)
    result.questions = [copy_question(q) for q in qs.Items]
    sublocations(result)
    return result


def copy_questionbank(bank, is_instructor=False, user=None):
    if is_instructor:
        result = bank.copy()
    else:
        questions = questionbank_question_chooser(bank, user=user)
        result = bank.copy(questions=questions)
    result.ntiid = bank.ntiid
    sublocations(result)
    return result


def copy_assignment(assignment):
    new_parts = []
    result = do_copy(assignment)
    for part in assignment.parts or ():
        new_part = do_copy(part)
        new_parts.append(new_part)
        new_part.question_set = copy_questionset(part.question_set)
    result.parts = new_parts
    sublocations(result)
    return result


def copy_evaluation(context, is_instructor=True):
    if IQAssignment.providedBy(context):
        result = copy_assignment(context)
    elif IQuestionBank.providedBy(context):
        result = copy_questionbank(context, is_instructor)
    elif IQuestionSet.providedBy(context):
        result = copy_questionset(context)
    elif IQuestion.providedBy(context):
        result = copy_question(context)
    elif IQPoll.providedBy(context):
        result = copy_poll(context)
    elif IQSurvey.providedBy(context):
        result = copy_survey(context)
    return result


def check_assignment(assignment, user=None):
    result = assignment
    if user is not None:
        ntiid = assignment.ntiid
        username = user.username
        # check r47694
        hack_map = r47694()
        if ntiid in hack_map and username in hack_map[ntiid]:
            result = copy_assignment(assignment)
            for question_set in result.iter_question_sets():
                make_sha224randomized(question_set.question_set)
                for question in question_set.questions:
                    make_sha224randomized(question)
                    for part in question.parts or ():
                        make_sha224randomized(part)
    return result


def assignment_has_file_part(assignment):
    for assignment_part in assignment.parts or ():
        question_set = assignment_part.question_set
        for question in question_set.Items:
            for question_part in question.parts or ():
                if IQFilePart.providedBy(question_part):
                    return True
    return False


def assignment_download_precondition(context, request=None, remoteUser=None):
    request = request if request is not None else get_current_request()
    remoteUser = remoteUser if remoteUser is not None else get_remote_user(request)
    username = request.authenticated_userid
    if not username:
        return False

    course = get_course_from_evaluation(context, remoteUser)
    if course is None or not has_permission(ACT_DOWNLOAD_GRADES, course, request):
        return False

    # Does it have a file part?
    return assignment_has_file_part(context)


def course_assignments_download_precondition(course, request=None, remoteUser=None):
    request = request if request is not None else get_current_request()
    remoteUser = remoteUser if remoteUser is not None else get_remote_user(request)
    username = request.authenticated_userid
    if not username:
        return False

    if course is None or not has_permission(ACT_DOWNLOAD_GRADES, course, request):
        return False

    # Is there at least one file part in the assignments?
    assignments = get_course_assignments(course, parent_course=True)
    for assignment in assignments:
        if assignment_has_file_part(assignment):
            return True
    return False


def get_current_metadata_attempt_item(user, course, assignment_ntiid):
    """
    For the user/course/assignment, return *the* currently ongoing attempt,
    if any.
    """
    assignment_metadata = component.queryMultiAdapter((course, user),
                                                      IUsersCourseAssignmentAttemptMetadata)
    # None due to no course given (tests or instructor practice submissions))
    if assignment_metadata is not None:
        item_container = assignment_metadata.get_or_create(assignment_ntiid)
        for item in item_container.values():
            if item.StartTime and not item.SubmitTime:
                return item

def replace_username(username):
    policy = component.queryUtility(IUsernameSubstitutionPolicy)
    if policy is not None:
        return policy.replace(username) or username
    return username


def get_course_from_request(request=None, params=None):
    request = get_current_request() if request is None else request
    course = ICourseInstance(request, None)
    if course is not None:
        return course
    try:
        params = request.params if params is None else params
        ntiid = params.get('course') \
             or params.get('entry') \
             or params.get('ntiid') \
             or params.get('context')
        # pylint: disable=too-many-function-args
        ntiid = urllib_parse.unquote(ntiid) if ntiid else None
        if ntiid:
            result = find_object_with_ntiid(ntiid)
            result = ICourseInstance(result, None)
            return result
    except AttributeError:
        pass
    return None


def get_package_from_request(request=None, params=None):
    request = get_current_request() if request is None else request
    package = IContentPackage(request, None)
    if package is not None:
        return package
    try:
        params = request.params if params is None else params
        ntiid = params.get('package') \
             or params.get('ntiid') \
             or params.get('context')
        # pylint: disable=too-many-function-args
        ntiid = urllib_parse.unquote(ntiid) if ntiid else None
        if ntiid:
            result = find_object_with_ntiid(ntiid)
            result = IContentPackage(result, None)
            return result
    except AttributeError:
        pass
    return None


def get_uid(context):
    return component.getUtility(IIntIds).getId(context)


@interface.implementer(IPrincipalSeedSelector)
class PrincipalSeedSelector(object):

    def __call__(self, principal=None):
        """
        With multiple submissions, all requests for assignment/assessed items
        (which may need to be randomized/unshuffled need to be requested in
        the context of a metadata attempt item, which stores the randomization
        seed for that particular attempt.

        For self-assessments, instructor submissions, we will not have a meta
        attempt and should just default to the user intid.
        """
        result = None
        request = get_current_request()
        meta_item = IUsersCourseAssignmentAttemptMetadataItem(request, None)
        if meta_item:
            result = meta_item.Seed
        else:
            user = get_user(principal, True)
            if user is not None:
                result = get_uid(user)
        return result


@interface.implementer(IQEvaluationContainerIdGetter)
class EvaluationContainerIdGetter(object):

    def __call__(self, item):
        for name in ('__home__', '__parent__'):
            parent = getattr(item, name, None)
            if IContentUnit.providedBy(parent):
                return parent.ntiid
            elif ICourseInstance.providedBy(parent):
                entry = ICourseCatalogEntry(parent)  # annotation
                return entry.ntiid
            elif ICourseCatalogEntry.providedBy(parent):
                return entry.ntiid
        return None


@interface.implementer(IRandomizedPartGraderUnshuffleValidator)
class RandomizedPartGraderUnshuffleValidator(object):

    def needs_unshuffled(self, context, creator):
        """
        Default to needs unshuffling. If we have a course or editor,
        we should not unshuffle (and our user is the submitter).
        """
        result = True
        # Need to have at least a question here for this to work
        # This only returns a single course.
        course = get_course_from_evaluation(context)
        if course is not None:
            user = get_remote_user()
            username = getattr(user, 'username', user)
            creator = getattr(creator, 'username', creator)
            creator = getattr(creator, 'id', creator)
            # If we have a creator, it probably means we're decorating.
            # If we don't have a creator, the remote user is the creator.
            if creator and creator != username:
                # Someone else (instructor) viewing/assessing something that
                # needs unshuffling.
                result = True
            else:
                # If not, return if submitter is and editor/instructor.
                is_editor = has_permission(ACT_CONTENT_EDIT, course) \
                         or is_course_instructor_or_editor(course, user)
                result = not is_editor
        return result
    needsUnshuffled = needs_unshuffled


@interface.implementer(ISolutionDecorationConfig)
class DefaultSolutionDecorationConfig(object):

    ShouldExposeSolutions = True


@interface.implementer(ISolutionDecorationConfig)
class DisabledSolutionDecorationConfig(object):

    ShouldExposeSolutions = False
