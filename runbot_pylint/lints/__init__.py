# -*- coding: utf-8 -*-
import textwrap

import astroid
import astroid.util
from pylint.checkers import BaseChecker, utils
from pylint.interfaces import IAstroidChecker


def register(linter):
    linter.register_checker(LiteralDictUpdate(linter))

BASE_ID = 78 # completely arbitrary value
def MSGID(code, severity='E'):
    return '{}{:02}{:02}'.format(severity, BASE_ID, code)

class LiteralDictUpdate(BaseChecker):
    """Looks for calls to dict.update and warns about .update calls whose
    arguments are "static dicts" in that the dict is created at the update
    callsite either through a literal dictionary parameter or through
    keyword arguments to update: dict.update(literal_dict) is a bunch of
    needless extra complexity, and while dict.update(**kw) has less redundancy
    than a bunch of dict[key] = value, it's also quite a bit slower:

    +----------+--------------+-------------------+---------------+
    |# of items|d[key] = value|d.update(key=value)|d.update({...})|
    +----------+--------------+-------------------+---------------+
    |         1|            1x|               3.5x|           6.3x|
    +----------+--------------+-------------------+---------------+
    |         5|            1x|               1.9x|           2.3x|
    +----------+--------------+-------------------+---------------+
    |        10|            1x|                 2x|           2.1x|
    +----------+--------------+-------------------+---------------+
    |        25|            1x|               2.2x|             2x|
    +----------+--------------+-------------------+---------------+

    That's in CPython 2.7 on OSX, pypy (4.0.1) has a pretty different
    profile though still always favoring setitem:

    - for 1 and 5 keys, all methods are within a few %
    - at 10 keys, the literal dict method takes 50% longer than
      setitem and update(**kw)
    - at 25 keys, the update(literal) method takes 3x the base, and
      the update(**kw) takes 11 times the base

    The performances of the setitem version are (as one would expect)
    linear on both interpreters, and pypy is faster (by a factor of 3
    to 10) in all cases but the 25-keys update(**kw) where ~0.6x
    slower.
    """
    __implements__ = [IAstroidChecker]

    name = MESSAGE_ID = 'update-literal'

    msgs = {
        MSGID(1): (
            "dict.update should not be called with %s. Use setitem or move to"
            " dict creation",
            MESSAGE_ID,
            textwrap.dedent("""
            Warn about dict.update being passed a literal dict or only
            keyword parameters. Using dict[k] = v is more efficient and faster
            """),
        )
    }

    @utils.check_messages(MESSAGE_ID)
    def visit_callfunc(self, node):
        if not isinstance(node.func, astroid.Attribute):
            return

        if node.func.attrname != 'update':
            return
        if not (node.args or node.keywords):
            return

        if not self.linter.is_message_enabled(self.MESSAGE_ID, line=node.fromlineno):
            return

        if node.args and isinstance(node.args[0], astroid.Dict):
            argtype = 'a literal dict'
        elif node.keywords and not node.args:
            argtype = 'only keyword arguments'
        else: # non-literal first arg + optional keywords
            return

        # TODO: suggest folding into initialization?
        # difficult:
        # * update must not be in a conditional
        # * dict shoud not have been updated since
        #
        # use node.scope().nodes_of_class(astroid.Name) to list all possible
        # uses, though beware aliasing

        self.add_message(self.MESSAGE_ID, args=(argtype,), node=node)

class LeftoverDebugging(BaseChecker):
    """ Looks for leftover debugging statements in PRs:
    """
    __implements__ = [IAstroidChecker]

    name = MESSAGE_ID = 'debugging-leftover'

    msgs = {
        MSGID(2): (
            "Leftover debugging statement %s",
            MESSAGE_ID,
            "Checks for statements looking like debugging leftover"
        ),
    }

    @utils.check_messages(MESSAGE_ID)
    def visit_print(self, node):
        """ Checks for print statements which are not redirected

        Redirected print statements can be more convenient than e.g. f.write
        to write to arbitrary streams (including but not limited to files),
        so they're eminently acceptable.

        .. todo:: handle the print function?
        """
        if not node.dest:
            self.add_message(
                self.MESSAGE_ID, args=node.as_string(), node=node)


    @utils.check_messages(MESSAGE_ID)
    def visit_assert(self, node):
        """ Checks for assert statements

        Technically they're not really debugging, but they're stripped by
        ``-O`` which we're using in the Windows packaging build process, so
        they probably shouldn't be in production code (outside of tests)
        """
        self.add_message(self.MESSAGE_ID, args=node.as_string(), node=node)

    # call signatures matching expectations to limit eventual false-positives
    # * .set_trace()
    # * .pm()
    # * .post_mortem([traceback])
    _CALL_MATCHES = (
        ('set_trace', 0),
        ('pm', 0),
        ('post_mortem', 0),
        ('post_mortem', 1),
    )
    @utils.check_messages(MESSAGE_ID)
    def visit_call(self, node):
        """ Checks for calls to methods ``set_trace``, ``post_mortem``, ``pm``

        The assumption is that they're debuggers matching the PDB API.

        Ideally we'd also match for the ``run*`` calls, but the fairly common
        naming makes that risky.

        Alternatively, we could define a somewhat arbitrary (and necessarily
        incomplete) blacklist of debugger modules and the builtin
        ``blacklisted-name`` lint.
        """
        if not isinstance(node.func, astroid.Attribute):
            return

        if (node.func.attrname, len(node.args)) in self._CALL_MATCHES:
            self.add_message(
                self.MESSAGE_ID, args=node.as_string(), node=node)
