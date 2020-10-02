#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.. $Id$
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

import re

from docutils import statemachine

from zope import component
from zope import interface

from zope.cachedescriptors.property import Lazy

from nti.app.assessment.evaluations import reference_directive_pattern

from nti.app.contentfolder.resources import is_internal_file_link

from nti.app.products.courseware.utils.exporter import save_resource_to_filer

from nti.assessment import IQSurvey

from nti.assessment.interfaces import IQEditableEvaluation

from nti.base._compat import text_
from nti.base._compat import bytes_

from nti.contentlibrary.interfaces import IContentOperator

from nti.contenttypes.presentation import IUserCreatedAsset

from nti.ntiids.ntiids import find_object_with_ntiid
from nti.ntiids.ntiids import hash_ntiid

logger = __import__('logging').getLogger(__name__)


class OperatorMixin(object):

    def __init__(self, *args):
        pass

    @Lazy
    def _figure_pattern(self):
        return reference_directive_pattern('course-figure')


@interface.implementer(IContentOperator)
@component.adapter(IQSurvey)
class SurveyContentsCourseFigureOperator(OperatorMixin):

    def _process(self, line, filer, result):
        modified = False
        # pylint: disable=no-member
        m = self._figure_pattern.match(line)
        if m is not None:
            reference = m.groups()[0]
            if is_internal_file_link(reference):
                internal = save_resource_to_filer(reference, filer)
                # pylint: disable=unused-variable
                __traceback_info__ = reference, internal
                if internal:
                    line = re.sub(reference, internal, line)
                    modified = True
        result.append(line)
        return modified

    def _replace_all(self, content, filer, result):
        modified = False
        input_lines = statemachine.string2lines(content)
        input_lines = statemachine.StringList(input_lines, '<string>')
        for idx in range(len(input_lines)):
            modified = self._process(input_lines[idx],
                                     filer, result) or modified
        return modified

    def operate(self, content, unused_context=None, **kwargs):
        if not content:
            return content
        filer = kwargs.get('filer')
        if filer is None:
            return content
        is_bytes = isinstance(content, bytes)
        content = text_(content) if is_bytes else content
        try:
            result = []
            modified = self._replace_all(content, filer, result)
            if modified:
                content = u'\n'.join(result)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Cannot operate on content")
        return bytes_(content) if is_bytes else content


@interface.implementer(IContentOperator)
@component.adapter(IQSurvey)
class SurveyContentsMediaRefOperator(object):

    def __init__(self, *args):
        pass

    @Lazy
    def _node_ref_patterns(self):
        result = []
        for prefix in ('ntivideoref', 'napollref' ):
            result.append(reference_directive_pattern(prefix))
        return result

    def _should_replace_ntiid(self, ntiid):
        """
        Only salt the ntiid if it is user created.
        """
        obj = find_object_with_ntiid(ntiid)
        return IUserCreatedAsset.providedBy(obj) \
            or IQEditableEvaluation.providedBy(obj)

    def _replace_refs(self, pattern, line, salt):
        m = pattern.match(line)
        if m is not None:
            ntiid = m.groups()[0]
            if self._should_replace_ntiid(ntiid):
                salted = hash_ntiid(ntiid, salt)
                line = re.sub(ntiid, salted, line)
        return bool(m is not None), line

    def _process_node_refs(self, input_lines, salt, idx, result):
        matched = False
        line = input_lines[idx]
        # pylint: disable=not-an-iterable
        for pattern in self._node_ref_patterns:
            matched, line = self._replace_refs(pattern, line, salt)
            if matched:
                result.append(line)
                break
        return matched, idx

    def _replace_all(self, content, salt, result):
        idx = 0
        modified = False
        input_lines = statemachine.string2lines(content)
        input_lines = statemachine.StringList(input_lines, '<string>')
        while idx < len(input_lines):
            matched, idx = self._process_node_refs(input_lines, salt, idx, result)
            if matched:
                modified = True
            else:
                result.append(input_lines[idx])
            idx += 1
        return modified

    def operate(self, content, unused_context=None, **kwargs):
        if not content:
            return content
        backup = kwargs.get('backup')
        if backup is None or backup:
            return content
        salt = kwargs.get('salt')
        if not salt and not backup:
            return content
        is_bytes = isinstance(content, bytes)
        content = text_(content) if is_bytes else content
        try:
            result = []
            if self._replace_all(content, salt, result):
                content = u'\n'.join(result)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Cannot operate on content")
        return bytes_(content) if is_bytes else content
