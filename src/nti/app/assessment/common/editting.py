from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

from pyramid import httpexceptions as hexc

from pyramid.threadlocal import get_current_request

from nti.app.assessment import MessageFactory as _

from nti.app.assessment.common.submissions import has_submissions

from nti.app.assessment.interfaces import IQAvoidSolutionCheck
from nti.app.assessment.interfaces import IQPartChangeAnalyzer

from nti.app.assessment.utils import get_course_from_request
from nti.app.assessment.utils import get_course_from_evaluation

from nti.app.externalization.error import raise_json_error


logger = __import__('logging').getLogger(__name__)


def pre_validate_question_change(question, externalValue):
    """
    Validate the proposed changes with the current question state
    (before modification), returning the parts that changed.
    """
    parts = externalValue.get('parts')
    check_solutions = not IQAvoidSolutionCheck.providedBy(question)
    course = get_course_from_request()
    if course is None:
        course = get_course_from_evaluation(question)
    regrade_parts = []
    if parts and has_submissions(question, course):
        for part, change in zip(question.parts, parts):
            analyzer = IQPartChangeAnalyzer(part, None)
            if analyzer is not None:
                # pylint: disable=too-many-function-args
                if not analyzer.allow(change, check_solutions):
                    raise_json_error(get_current_request(),
                                     hexc.HTTPUnprocessableEntity,
                                     {
                                         'message': _(u"Question has submissions. It cannot be updated."),
                                         'code': 'CannotChangeObjectDefinition',
                                     },
                                     None)
                if analyzer.regrade(change):
                    regrade_parts.append(part)
    return regrade_parts
