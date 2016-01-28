# -*- coding: utf-8 -*-
import logging
import re

import requests

from openerp import api, models, fields
from pylint.lint import fix_import_path

from . import lint

_logger = logging.getLogger(__name__)


class RunbotBranch(models.Model):
    _inherit = 'runbot.branch'

    lint = fields.Selection([
        ('empty', "not linted"),
        ('pending', "linting pull request"),
        ('success', "lint succeeded"),
        ('failure', "lint failed"),
        ('error', "error while linting"),
    ], default='empty', required=True)

class runbot_build(models.Model):
    _inherit = "runbot.build"

    def _lint_state_to(self, state, description=None):
        if state not in ('pending', 'success', 'error', 'failure'):
            state = 'failure'
            description = "Unknown linting state " + state

        _logger.info("lint state of %s changed to %s (%s)",
                     self.name, state, description)
        self.branch_id.lint = state
        self._update_status({
            'state': state,
            'description': description or "Linting",
            'context': 'ci/lint',
        })

    @api.model
    def job_05_check_lint(self, build, lock_path, log_path):
        p = build.branch_id._get_pull_info()
        if not p:
            _logger.info("Found no pull information, ignoring linting")
            return -2

        build._lint_state_to('pending')

        diff = build.repo_id._api_request(
            build.repo_id._expand_api_uri(
                '/repos/:owner/:repo/pulls/:number',
                number=p['number']
            ),
            headers={'Accept': 'application/vnd.github.v3.diff'},
            stream=True,
        )
        if diff.status_code != requests.codes.ok:
            _logger.warn("Failed to get diff for branch %s: %s",
                         build.branch_id, diff.text)
            build._lint_state_to('error', description="Failed to fetch diff")
            return -2

        moved_path_map = {}
        patch_lines = []
        # store converted (moved) paths in moved_path_map so it's possible to
        # revert from moved on-disk paths to original in-repo paths (the
        # latter being what's needed to annotate github PRs)
        if build.server_match == self.INCLUDED_SERVER:
            matcher = _server_repo_paths
        else:
            matcher = _modules_repo_paths

        for line in diff.iter_lines(decode_unicode=True):
            tr, n = matcher.subn('\g<prefix>openerp/addons/\g<postfix>', line)
            patch_lines.append(tr)
            if n:
                moved_path_map[tr[6:]] = line[6:]

        reporter = lint.RunbotReporter()

        # since all modules have been moved to openerp/addons, we can just
        # lint openerp and it'll recurse
        paths = [build.path('openerp')]

        with fix_import_path(paths):
            self.env['runbot_pylint.config'].search([], limit=1)._init_linter(
                reporter=reporter,
                diff=patch_lines,
                refpath=build.path()
            ).check(paths)

        if not reporter.messages:
            # all's well
            build._lint_state_to('success')
            return -2

        # printing of report to stdout?
        # reporter.display_reports(None)

        self._report_failure(build, p, reporter, patch_lines, moved_path_map)

        return -2

    def _report_failure(self, build, p, reporter, patch_lines, moved_path_map):
        failure_message = "Detected {} linting issues".format(len(reporter.messages))
        cr, uid, context = build._cr, build._uid, build._context

        Logging = self.pool['ir.logging']
        Logging.create(cr, uid, {
            'build_id': build.id,
            'level': 'WARNING',
            'type': 'runbot',
            'name': 'lint',
            'message': failure_message,
            'path': 'runbot',
            'func': 'odoo.runbot',
            'line': '0',
        }, context=context)
        prefix = build.path('')
        for m in reporter.messages:
            path = m['path'].replace(prefix, '')
            original_path = moved_path_map.get(path, path)
            Logging.create(cr, uid, {
                'build_id': build.id,
                'level': 'INFO',
                'type': 'runbot',
                'name': original_path,
                'message': m['message'],
                'path': original_path,
                'func': m['type'],
                'line': str(m['line']),
            })
        build._lint_state_to('failure', description=failure_message)

        # format messages as {file_path: {line: {type, message}}}
        # possible issue: multiple warnings on the same line of the same file?
        # messages = {}
        # for m in reporter.messages:
        #     messages.setdefault(m['path'].replace(prefix, ''), {})[
        #         m['line']] = {
        #         'message': m['message'],
        #         'type': m['type'],
        #     }
        # try:
        #     for f, lineno, msg in self._match_messages_to_patch(
        #             messages, moved_path_map, patch_lines):
        #         comment = self._format_lint_message_for_pr(msg)
        #         self._comment_on_pr(build, p, f, lineno, comment)
        # except Exception:
        #     _logger.exception("Trying to find out patched lines failed")
        #
        #     build._lint_state_to(
        #             'failure',
        #             "Something went wrong with the inline comments generation"
        #     )
        # else:
        #     build._lint_state_to(
        #             'failure',
        #             "Detected {} linting issues".format(
        #                 len(reporter.messages))
        #     )

    def _match_messages_to_patch(self, messages, moved_path_map, patch_lines):
        """ Take all of the lint ``messages`` and find out which section of
        the "patch file" they apply to.

        :returns: iterator of (filename, lineno, message)

        .. warning:: ``lineno`` is the line number in the section of the
                     ``patch_file`` for the file, not the absolute line number
                     in the patch file
        """
        hunk = None
        for patch_line in patch_lines:
            if patch_line.startswith(u'+++ b/'):
                filename = patch_line[6:]
                if filename in messages:
                    hunk = {'filename': filename, 'patch_lineno': 0}
                else:
                    # no message for the file, skip until next file
                    # section
                    hunk = None
                continue

            if hunk is None: continue

            # running line number within a file's section (as that's what
            # github wants for inline messages), 0-indexed starting from
            # the hunk header (the line following the "new file" header is
            # line 1 of its section)
            hunk['patch_lineno'] += 1

            # hunk header, get number for current line in "real" file
            if patch_line.startswith(u'@@'):
                offset = lint._offset.match(patch_line)
                # we only care about the real line offset
                hunk['real_lineno'] = int(offset.group(1))
                continue

            # if pylint has a message for the current *real* line
            msg = messages[hunk['filename']].get(hunk['real_lineno'])
            # and the current patch line was *added* (to avoid annotating
            # a ton of lines when there's a message for an added line
            # following a bunch of removed lines)
            if msg and patch_line.startswith('+'):
                yield (
                    # get original path if moved, otherwise use physical path
                    moved_path_map.get(hunk['filename'], hunk['filename']),
                    # not sure why this should be offset back
                    hunk['patch_lineno'] - 1,
                    msg
                )

            # post-increment real_lineno since the header provides the
            # 1-indexed lineno of the first line of the hunk, but only if
            # the current line wasn't *removed* by the patch
            if not patch_line.startswith('-'):
                hunk['real_lineno'] += 1

    def _comment_on_pr(self, build, pr_info, section_file, section_line, comment):
        """ format and add ``lint_message`` to ``pr_info`` of line
        ``section_line`` of patched file ``section_file``.

        ``section_line`` is the offset from the ``section_file`` header within
        the patch file, it's neither the line number in the patch file nor the
        line number in the actual file (patched or not).
        """
        payload = {
            'commit_id': build.name,  # or pr_info.head.sha
            'path': section_file,
            'position': section_line,
            'body': comment,
        }
        _logger.info("Annotating PR %d with %s", pr_info['number'], payload)
        build.repo_id._api_request(
            build.repo_id._expand_api_uri(
                '/repos/:owner/:repo/pulls/:number/comments',
                number=pr_info['number']
            ),
            payload=payload,
        ).raise_for_status()

    def _format_lint_message_for_pr(self, msg):
        """ Format a pylint message to a PR comment body.

        * The first line is a text description of the error
        * If any, following lines are literal content (a bit of code with a
          pointer to the error location)
        """
        message, details = (msg['message'] + '\n').split('\n', 1)
        body = "Lint issue: {message}".format(type=msg['type'], message=message)
        if not details:
            return body

        return """{header}
```
{details}```
""".format(header=body, details=details)

# embedded server -> runbot moves all addons/* paths are to
# openerp/addons/*
_server_repo_paths = re.compile(r"""
    (?P<prefix>
        (\+\+\+|---)
        \s
        [a|b]/ # a or b prefix, ignore /dev/null
    )
    addons/ # only match addons/ stuff
    (?P<postfix>.*)
""", re.VERBOSE | re.DOTALL)

# modules-only repository, ~all directories at root are modules moved to
# openerp/addons (theoretically should only match whose with a manifest but
# we don't have the info here so...
_modules_repo_paths = re.compile(r"""
    (?P<prefix>
        (\+\+\+|---)
        \s
        [a|b]/
    )
    # nothing inbetween, we want the whole thing
    (?P<postfix>.*)
""", re.VERBOSE | re.DOTALL)
