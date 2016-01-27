# -*- coding: utf-8 -*-

import os.path
import pprint
import re

from pylint import lint
from pylint.reporters import BaseReporter

_offset = re.compile(r'''
@@
\s
-\d+(?:,\d+)?
\s
\+(\d+)(?:,(\d+))?
\s
@@
''', re.VERBOSE)

def _changed_lines(ref_path, difflines):
    """ stores which lines of which files have been added by a patch. We
    only lint the added lines, not the context lines, otherwise as developers
    fix lint errors the context expands and they ultimately end up editing the
    whole file.

    OTOH not sure how this handles messages which span multiple lines e.g.
    ordering of import statements
    """
    lines_map = {}
    for line in difflines:
        if line.startswith('+++ b/'): # destination file
            lines = []
            # current file
            current_file = line[6:].strip()
            lines_map[os.path.join(ref_path, current_file)] = lines
            lineno = 1
        elif line.startswith('@@'): # new hunk, get destination offset
            r = _offset.match(line)
            lineno = int(r.group(1))
        elif line.startswith(' '): # context line, increment offset
            lineno += 1
        elif line.startswith('+'): # changed line in destination,
            # add to set lineno is the number of the *current*
            # line, so store first then increment for next line
            lines.append(lineno)
            lineno += 1
        else:
            # ignore all other lines (---, -, diff, index)
            pass
    return lines_map

class Linter(lint.PyLinter):
    """ Custom PyLinter able to filter messages based on a diff: only messages
    affecting a `+` line (changed or new) will be allowed, the rest is
    ignored.

    Since PyLint doesn't support line ranges/sets for messages, this will
    probably ignore messages which could have been displayed.
    """
    def __init__(self, *args, **kwargs):
        self._lines_map = None
        diff_it = kwargs.pop('diff', None)
        if diff_it:
            self._lines_map = _changed_lines(kwargs.pop('refpath'), diff_it)
        super(Linter, self).__init__(*args, **kwargs)

    def is_message_enabled(self, msg_descr, line=None, confidence=None):
        # ignore pointless statement warning in manifest file
        if (self.current_file or '').endswith('__openerp__.py'):
            # msg_descr can be either the symbolic code or the prefixed
            # numerical code, get the canonical symbolic code
            message_definition = self.msgs_store.check_message_id(msg_descr)
            if message_definition.symbol == 'pointless-statement':
                return False

        # there are cases where current_file is None, not sure what they mean
        # but we'll default to leaving them through
        if self.current_file and self._lines_map is not None:
            lines = self._lines_map.get(self.current_file)
            if not lines or line not in lines:
                return False

        return super(Linter, self).is_message_enabled(
            msg_descr, line=line, confidence=confidence)

    def expand_files(self, modules):
        results = super(Linter, self).expand_files(modules)
        if self._lines_map is None:
            return results

        _allowed = self._lines_map
        return [result for result in results if result['path'] in _allowed]

class RunbotReporter(BaseReporter):
    def __init__(self, output=None):
        super(RunbotReporter, self).__init__(output)
        self.messages = []

    def _display(self, layout):
        if self.messages:
            pprint.pprint(self.messages, stream=self.out, indent=4)

    def handle_message(self, message):
        self.messages.append({
            'path': message.path,
            'line': message.line,
            'message': message.msg,
            'type': message.category,
        })
