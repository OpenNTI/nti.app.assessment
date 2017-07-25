#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import print_function, absolute_import, division
__docformat__ = "restructuredtext en"

from zope import interface

from zope.container.constraints import contains
from zope.container.constraints import containers

from zope.container.interfaces import IContained
from zope.container.interfaces import IContainer
from zope.container.interfaces import IContainerNamesContainer

from zope.interface.interfaces import ObjectEvent
from zope.interface.interfaces import IObjectEvent

from zope.security.permission import Permission

from nti.assessment.interfaces import IQAssignment
from nti.assessment.interfaces import IQEvaluation
from nti.assessment.interfaces import IQAssignmentSubmission
from nti.assessment.interfaces import IQAssignmentSubmissionPendingAssessment

from nti.assessment.interfaces import IQInquiry
from nti.assessment.interfaces import IQInquirySubmission
from nti.assessment.interfaces import IQAggregatedInquiry

from nti.dataserver.interfaces import IUser
from nti.dataserver.interfaces import ICreated
from nti.dataserver.interfaces import ILastViewed
from nti.dataserver.interfaces import ILastModified
from nti.dataserver.interfaces import ITitledContent
from nti.dataserver.interfaces import IModeledContent
from nti.dataserver.interfaces import IUserGeneratedData
from nti.dataserver.interfaces import IModeledContentBody
from nti.dataserver.interfaces import INeverStoredInSharedStream
from nti.dataserver.interfaces import IShouldHaveTraversablePath
from nti.dataserver.interfaces import ExtendedCompoundModeledContentBody

from nti.namedfile.interfaces import IFileConstrained

from nti.schema.field import Int
from nti.schema.field import Dict
from nti.schema.field import List
from nti.schema.field import Float
from nti.schema.field import Number
from nti.schema.field import Object
from nti.schema.field import ValidTextLine

ACT_VIEW_SOLUTIONS = Permission('nti.actions.assessment.view_solutions')
ACT_DOWNLOAD_GRADES = Permission('nti.actions.assessment.download_grades')


class IUsersCourseAssignmentSavepoints(IContainer,
                                       IContained,
                                       IShouldHaveTraversablePath):
    """
    A container for all the assignment save points in a course, keyed by username.
    """
    contains('.IUsersCourseAssignmentSavepoint')

    def has_assignment(assignment_id):
        """
        returns true if there is savepoint for the specified assigment
        """


class IUsersCourseAssignmentSavepoint(IContainer,
                                      IContained,
                                      IShouldHaveTraversablePath):
    """
    A :class:`IContainer`-like object that stores the save point of
    assignments for a particular user in a course. The keys of this
    object are :class:`IAssignment` IDs (this class may or may not
    enforce that the assignment ID is actually scoped to the course it
    is registered for). The values are instances of :class:`.IQAssignmentSubmission`.
    """

    contains('.IUsersCourseAssignmentSavepointItem')
    containers(IUsersCourseAssignmentSavepoints)
    __setitem__.__doc__ = None

    owner = Object(IUser, 
                   required=False, 
                   title=u"The user this save point is for.")
    owner.setTaggedValue('_ext_excluded_out', True)

    Items = Dict(title=u'For externalization only, a copy of the items', 
                 readonly=True)

    def recordSubmission(submission, event=False):
        """
        When a user submits an assignment for save point call this method to record
        that fact. If a submission has already been recorded, this will
        replace the previous one

        :param submission: The original :class:`.IQAssignmentSubmission`
                the user provided. We will become part of the lineage
                of this object and all its children objects (they will
                be set to the correct __parent__ relationship within the part/question
                structure).

        :param event: Flag to avoid sending an add/modified event

        :return: The new :class:`.IUsersCourseAssignmentSavepointItem` representing
                         the record of this submission.
        """

    def removeSubmission(submission, event=False):
        """
        remove a submission

        :param submission: The :class:`.IQAssignmentSubmission` to remove
        :param event: Flag to avoid sending a removal/modified event
        """


class IUsersCourseAssignmentSavepointItem(IContained,
                                          ILastModified,
                                          ICreated,
                                          IShouldHaveTraversablePath):

    containers(IUsersCourseAssignmentSavepoint)
    __parent__.required = False

    Submission = Object(IQAssignmentSubmission, required=False)


class IUsersCourseAssignmentHistories(IContainer,
                                      IContained,
                                      IShouldHaveTraversablePath):
    """
    A container for all the assignment histories in a course, keyed
    by username.
    """
    contains('.IUsersCourseAssignmentHistory')


class IUsersCourseAssignmentHistory(IContainer,
                                    ILastViewed,
                                    IContained,
                                    IShouldHaveTraversablePath):
    """
    A :class:`IContainer`-like object that stores the history of
    assignments for a particular user in a course. The keys of this
    object are :class:`IAssignment` IDs (this class may or may not
    enforce that the assignment ID is actually scoped to the course it
    is registered for). The values are instances of
    :class:`.IUsersCourseAssignmentHistoryItem`.

    Implementations of this object are typically found as a
    multi-adapter between a particular :class:`.ICourseInstance` and
    an :class:`.IUser`. Their ``__parent__`` will be the course
    instance; therefore, items stored in this object will have the
    course they were assigned by in their lineage.

    This object claims storage and ownership of the objects given to it through
    :meth:`recordSubmission`. Lifecycle events will be emitted for
    the creation of the :class:`IUsersCourseAssignmentHistoryItem`,
    the addition of that item, and finally the addition of the pending assessment
    (at that point, the submission's and pending assessment's ``__parent__``
    will be the history item which in turn will be parented by this object.)
    """

    contains('.IUsersCourseAssignmentHistoryItem')
    containers(IUsersCourseAssignmentHistories)
    __setitem__.__doc__ = None

    owner = Object(IUser,
				   required=False, 
				   title=u"The user this history is for.")
    owner.setTaggedValue('_ext_excluded_out', True)

    Items = Dict(title=u'For externalization only, a copy of the items',
                 readonly=True)

    def recordSubmission(submission, pending_assessment):
        """
        When a user submits an assignment, call this method to record
        that fact. If a submission has already been recorded, this will
        raise the standard container error, so use ``in`` first of that's
        a problem.

        :param submission: The original :class:`.IQAssignmentSubmission`
                the user provided. We will become part of the lineage
                of this object and all its children objects (they will
                be set to the correct __parent__ relationship within the part/question
                structure).
        :param pending_assessment: The in-progress assessment object
                initially derived from the submission (and that the user
                will store). We will become part of the lineage of this object.
        :return: The new :class:`.IUsersCourseAssignmentItem` representing
                the record of this submission.
        """


class IUsersCourseAssignmentHistoryItemFeedbackContainer(IContainerNamesContainer,
                                                         ICreated,
                                                         ILastModified,
                                                         IShouldHaveTraversablePath):
    """
    A container for feedback items.
    """
    contains('.IUsersCourseAssignmentHistoryItemFeedback')

    __setitem__.__doc__ = None

    Items = List(title=u"The contained feedback items",
                 description=u"Unlike forums, we expect very few of these, so we "
                 u"inline them for externalization.",
                 readonly=True)


class IUsersCourseSubmissionItem(IContained, IShouldHaveTraversablePath):
    """
    Marker interface for course submission items
    """


class IUsersCourseAssignmentHistoryItem(ICreated,
                                        ILastModified,
                                        IUsersCourseSubmissionItem):
    """
    A record of something being submitted for an assignment.

    .. note:: This will probably grow much.
    """
    containers(IUsersCourseAssignmentHistory)
    __parent__.required = False

    # Recall that the implementation of AssignmentSubmission is NOT Persistent.
    Submission = Object(IQAssignmentSubmission, required=False)

    # This object is persistent, and should be modified in place if needed.
    pendingAssessment = Object(IQAssignmentSubmissionPendingAssessment,
                               required=False)

    Feedback = Object(IUsersCourseAssignmentHistoryItemFeedbackContainer,
                      required=False)

    FeedbackCount = Int(title=u"How many feedback items", default=0)

    Assignment = Object(IQAssignment, 
						title=u"The assigment that generated this item",
                        required=False)
    Assignment.setTaggedValue('_ext_excluded_out', True)


class IUsersCourseAssignmentHistoryItemSummary(IContained,
                                               ILastModified,
                                               ICreated,
                                               IShouldHaveTraversablePath):
    """
    A quick summary of a complete history item, typically for
    fast externalization purposes.
    """

    FeedbackCount = Int(title=u"How many feedback items", default=0)

    SubmissionCreatedTime = Number(title=u"The timestamp at which the submission object was created.",
                                   description=u"Typically set automatically by the object.",
                                   default=0.0)


class IUsersCourseAssignmentHistoryItemFeedback(IContained,
                                                ITitledContent,
                                                IModeledContent,
                                                IFileConstrained,
                                                IUserGeneratedData,
                                                IModeledContentBody,
                                                INeverStoredInSharedStream,
                                                IShouldHaveTraversablePath):
    """
    A feedback item on a history item.

    Notice that these are not :class:`.IThreadable`; all feedback
    is considered to be top-level.
    """

    # Adds __parent__ as required
    containers(IUsersCourseAssignmentHistoryItemFeedbackContainer)
    __parent__.required = False

    body = ExtendedCompoundModeledContentBody()


class IUsersCourseAssignmentMetadataContainer(IContainer,
                                              IContained,
                                              IShouldHaveTraversablePath):
    """
    A container for all the assignment meta data in a course, keyed by username.
    """
    contains('.IUsersCourseAssignmentMetadata')


class IUsersCourseAssignmentMetadata(IContainer,
                                     IContained,
                                     IShouldHaveTraversablePath):
    """
    A :class:`IContainer`-like object that stores metadata of
    assignments for a particular user in a course. The keys of this
    object are :class:`IAssignment` IDs (this class may or may not
    enforce that the assignment ID is actually scoped to the course it
    is registered for). The values are instances of :class:`.IUsersCourseAssignmentMetadataItem`.
    """

    contains('.IUsersCourseAssignmentMetadataItem')
    containers(IUsersCourseAssignmentMetadataContainer)
    __setitem__.__doc__ = None

    owner = Object(IUser, 
				   required=False, 
				   title=u"The user this metadata is for.")
    owner.setTaggedValue('_ext_excluded_out', True)

    Items = Dict(title=u'For externalization only, a copy of the items', 
				 readonly=True)


class IUsersCourseAssignmentMetadataItem(interface.Interface):
    containers(IUsersCourseAssignmentMetadata)
    __parent__.required = False

    StartTime = Float(title=u"Assignment Start time", required=False)
    Duration = Float(title=u"Assignment Duration", required=False)


class IUsersCourseInquiries(IContainer,
                            IContained,
                            IShouldHaveTraversablePath):
    """
    A container for all the survey/poll submissions in a course, keyed by username.
    """
    contains('.IUsersCourseInquiry')


class IUsersCourseInquiry(IContainer,
                          IContained,
                          IShouldHaveTraversablePath):
    """
    A :class:`IContainer`-like object that stores the history of
    inquiries for a particular user in a course. The keys of this
    object are :class:`IQInquiry` IDs (this class may or may not
    enforce that the Inquiry ID is actually scoped to the course it
    is registered for). The values are instances of
    :class:`.IUsersCourseInquiryItem`.

    Implementations of this object are typically found as a
    multi-adapter between a particular :class:`.ICourseInstance` and
    an :class:`.IUser`. Their ``__parent__`` will be the course
    instance; therefore, items stored in this object will have the
    course they were assigned by in their lineage.

    This object claims storage and ownership of the objects given to it through
    :meth:`recordSubmission`. Lifecycle events will be emitted for
    the creation of the :class:`IUsersCourseInquiryItem`
    """

    contains('.IUsersCourseInquiryItem')
    containers(IUsersCourseInquiries)
    __setitem__.__doc__ = None

    owner = Object(IUser, required=False,
                   title=u"The user this inquiry is for.")
    owner.setTaggedValue('_ext_excluded_out', True)

    Items = Dict(title=u'For externalization only, a copy of the items',
                 readonly=True)

    def recordSubmission(submission):
        """
        When a user submits an inquiry, call this method to record
        that fact. If a submission has already been recorded, this will
        raise the standard container error, so use ``in`` first of that's
        a problem.

        :param submission: The original :class:`.IQInquirySubmission`
                the user provided. We will become part of the lineage
                of this object and all its children objects (they will
                be set to the correct __parent__ relationship within the part/question
                structure).
        :param event: Flag to avoid sending an add/modified event

        :return: The new :class:`.IUsersCourseInquiryItem` representing
                the record of this submission.
        """

    def removeSubmission(submission):
        """
        remove a submission

        :param submission: The submission to remove
        """


class IUsersCourseInquiryItem(ICreated,
                              ILastModified,
                              IUsersCourseSubmissionItem):
    """
    A record of something being submitted for a survey/poll.
    """
    containers(IUsersCourseInquiry)
    __parent__.required = False

    # Recall that the implementation of IQInquirySubmission is NOT Persistent.
    Submission = Object(IQInquirySubmission, required=False)

    Inquiry = Object(IQInquiry, 
                     title=u"The inquiry that generated this item",
                     required=False)
    Inquiry.setTaggedValue('_ext_excluded_out', True)

    inquiryId = ValidTextLine(title=u"Survey/Poll id", required=False)
    inquiryId.setTaggedValue('_ext_excluded_out', True)


class IUsersCourseInquiryItemResponse(interface.Interface):
    Submission = Object(IUsersCourseInquiryItem, required=True)
    Aggregated = Object(IQAggregatedInquiry, required=False)


class ICourseInquiryCatalog(interface.Interface):
    """
    Provides access to the surveys/polls related to a course.

    Typically this will be registered as an adapter
    from the :class:`.ICourseInstance`.
    """

    def iter_inquiries():
        """
        Return the inquiry objects.

        Recall that surveys typically will have their 'home'
        content unit in their lineage.
        """


class ICourseAggregatedInquiries(IContainer,
                                 IContained,
                                 IShouldHaveTraversablePath):
    """
    A container for all the aggreated survey and polls key by their ntiids
    """
    contains(IQAggregatedInquiry)


class IQEvaluations(IContainer,
                    IContained,
                    IShouldHaveTraversablePath):
    """
    A container for all the evaluation objects in a context
    """
    contains(IQEvaluation)

    def replace(old, new, event=False):
        """"
        replace the old evalutation object with the new one
        """


class ICourseEvaluations(IQEvaluations):
    """
    A container for all the evaluation objects in a course
    """


class IContentPackageEvaluations(IQEvaluations):
    """
    A container for all the evaluation objects in a content package
    """
    

class IQPartChangeAnalyzer(interface.Interface):
    """
    Marker interface for a question part adapter to analyze an update to it
    """

    def validate(part=None, check_solutions=True):
        """
        validate this or the specified part

        :param check_solutions: Validate part solutions
        """

    def allow(change, check_solutions=True):
        """
        Given the specified change it returns whether or not it is allowed

        :param change: Part update
        :param check_solutions: Validate change/part solutions
        """

    def regrade(change):
        """
        Given the specified change it returns whether or not the part must be regraded

        :param change: Part update
        """


class IQAvoidSolutionCheck(interface.Interface):
    """
    Marker interface to avoid solution checks
    """
IQAvoidSolutionCheck.setTaggedValue('_ext_is_marker_interface', True)


class IObjectRegradeEvent(IObjectEvent):
    pass


@interface.implementer(IObjectRegradeEvent)
class ObjectRegradeEvent(ObjectEvent):
    pass


class IRegradeEvaluationEvent(IObjectRegradeEvent):
    parts = interface.Attribute("Change parts")
IRegradeQuestionEvent = IRegradeEvaluationEvent


@interface.implementer(IRegradeEvaluationEvent)
class RegradeEvaluationEvent(ObjectRegradeEvent):

    def __init__(self, obj, parts=()):
        super(RegradeEvaluationEvent, self).__init__(obj)
        self.parts = parts or ()
RegradeQuestionEvent = RegradeEvaluationEvent
