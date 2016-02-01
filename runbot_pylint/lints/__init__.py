# -*- coding: utf-8 -*-
import textwrap

import astroid
from pylint.checkers import BaseChecker, utils
from pylint.interfaces import IAstroidChecker


def register(linter):
    linter.register_checker(LiteralDictUpdate(linter))


class LiteralDictUpdate(BaseChecker):
    __implements__ = [IAstroidChecker]

    name = 'update-literal'

    MESSAGE_ID = 'update-literal'

    msgs = {
        'W9999': (
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
