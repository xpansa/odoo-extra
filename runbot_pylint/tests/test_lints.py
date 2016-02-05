# -*- coding: utf-8 -*-
import unittest

import astroid
from pylint.testutils import CheckerTestCase, UnittestLinter

from ..lints import LeftoverDebugging, LiteralDictUpdate


# support line= kwarg in is_message_enabled of mock linter cf PyCQA/pylint/pull/809
class CheckerLinter(UnittestLinter):
    def is_message_enabled(self, *args, **kwargs):
        return True
class CheckerCase(CheckerTestCase):
    def setUp(self):
        self.linter = CheckerLinter()
        self.checker = self.CHECKER_CLASS(self.linter) # pylint: disable=not-callable
        for key, value in self.CONFIG.iteritems():
            setattr(self.checker.config, key, value)
        self.checker.open()


class TestDictUpdate(CheckerCase):
    CHECKER_CLASS = LiteralDictUpdate

    def test_literal_param(self):
        self.walk(astroid.parse("""
        d = {}
        d.update({'foo': 5})
        """))
        self.assertNotEqual(
            self.linter.release_messages(),
            []
        )

    @unittest.expectedFailure
    def test_literal_var(self):
        """ needs control flow analysis to see that the dict is being updated
        with a literal: parameter is a name, which was bound to a literal
        dict, which has no update path preceding the update call... a bit
        tough and couldn't find CFA tools in pylint
        """
        self.walk(astroid.parse("""
        d1 = {}
        d2 = {'a': 9}
        d1.update(d2)
        """))
        self.assertNotEqual(
            self.linter.release_messages(),
            []
        )

    def test_update_kwargs(self):
        self.walk(astroid.parse("""
        d = {}
        d.update(foo=5)
        """))
        self.assertNotEqual(
            self.linter.release_messages(),
            []
        )
    def test_update_both(self):
        self.walk(astroid.parse("""
        d = {}
        d.update({'foo': 5}, bar=4)
        """))
        self.assertNotEqual(
            self.linter.release_messages(),
            []
        )

    def test_update_nonliteral(self):
        with self.assertNoMessages():
            self.walk(astroid.parse("""
            d = {}
            d.update(zip(range(5), range(5, 10)))
            """))

        with self.assertNoMessages():
            self.walk(astroid.parse("""
            d = {}
            d.update(zip(range(5), range(5, 10)), other=3)
            """))

class TestLeftoverDebugging(CheckerCase):
    CHECKER_CLASS = LeftoverDebugging

    def test_print(self):
        self.walk(astroid.parse("""
        print "foo"
        """))
        self.assertNotEqual(
            self.linter.release_messages(),
            []
        )
    def test_redirected_print(self):
        with self.assertNoMessages():
            self.walk(astroid.parse("""
            with open('~/.hohoho', 'wb') as f:
                print >>f, "happy feast of winterveil"
            """))

    def test_assert(self):
        self.walk(astroid.parse("""
        assert False
        """))
        self.assertNotEqual(self.linter.release_messages(), [])

        self.walk(astroid.parse("""
        assert True
        """))
        self.assertNotEqual(self.linter.release_messages(), [])

    def test_debuggers(self):
        self.walk(astroid.parse("""
        pdb.set_trace()
        """))
        self.assertNotEqual(self.linter.release_messages(), [])

        self.walk(astroid.parse("""
        ipdb.post_mortem()
        """))
        self.assertNotEqual(self.linter.release_messages(), [])

        self.walk(astroid.parse("""
        pudb.pm()
        """))
        self.assertNotEqual(self.linter.release_messages(), [])
