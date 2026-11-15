"""Tests for memory.cli.main: subcommand registration, empty-store behaviour,
JSON output contract, and argparse errors.

--agentic schema coverage lives in test_agentic.py and is not duplicated here.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest

import memory.cli as memory_cli
from tests.memory_tests.fixtures import MemoryTestCase

_KNOWN_SUBCOMMANDS = {
    "list",
    "show",
    "search",
    "validate",
    "stores",
    "consolidate",
    "export",
    "import",
    "backup",
    "graduate",
}


def _invoke(argv: list[str]) -> tuple[int, str, str]:
    """Call memory.cli.main(argv) and return (rc, stdout, stderr)."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = memory_cli.main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _invoke_expecting_exit(test: unittest.TestCase, argv: list[str]) -> tuple[object, str, str]:
    """Run argv, assert argparse raised SystemExit, return (code, stdout, stderr)."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with (
        contextlib.redirect_stdout(out_buf),
        contextlib.redirect_stderr(err_buf),
        test.assertRaises(SystemExit) as ctx,
    ):
        memory_cli.main(argv)
    return ctx.exception.code, out_buf.getvalue(), err_buf.getvalue()


class TestBareSubcommandsWithNoStores(MemoryTestCase):
    """With an empty HOME, each subcommand exits with its documented code."""

    # Exit codes when no stores exist and no other args are given.
    EXPECTED = {
        "list": 0,  # "No memory stores found." -> 0
        "show": 1,  # slug is required -> validation error
        "validate": 0,  # nothing to check -> clean
        "stores": 0,
        "consolidate": 0,  # nothing discovered -> 0
        "export": 1,  # needs --slug/--type/--all
        "backup": 1,  # needs --store or --all-stores
        "graduate": 1,  # slug is required
    }

    def test_exit_codes(self) -> None:
        for subcmd, expected in self.EXPECTED.items():
            with self.subTest(subcmd=subcmd):
                rc, _, _ = _invoke([subcmd])
                self.assertEqual(rc, expected)

    def test_positional_required_by_argparse(self) -> None:
        for subcmd in ("search", "import"):
            with self.subTest(subcmd=subcmd):
                code, out, err = _invoke_expecting_exit(self, [subcmd])
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("required", err)


class TestSubcommandJsonOutput(MemoryTestCase):
    """Read-only subcommands emit parseable JSON under --format json, even when empty."""

    def test_empty_json_is_an_empty_list(self) -> None:
        for argv in (["list"], ["stores"], ["validate"], ["search", "memory", "--all-stores"]):
            with self.subTest(argv=argv):
                rc, out, _ = _invoke([*argv, "--format", "json"])
                self.assertEqual(rc, 0)
                self.assertEqual(json.loads(out), [])


class TestUnknownSubcommand(MemoryTestCase):
    """An unknown subcommand exits 2 with the error on stderr, stdout clean."""

    def test_unknown_subcommand(self) -> None:
        code, out, err = _invoke_expecting_exit(self, ["never-heard-of-this"])
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)
        self.assertNotIn("never-heard-of-this", out)


class TestKnownSubcommandsPresent(unittest.TestCase):
    """The parser registers exactly the expected subcommand set."""

    def test_all_expected_subcommands_registered(self) -> None:
        parser = memory_cli.app.build_parser()
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        self.assertEqual(len(actions), 1)
        self.assertEqual(set(actions[0].choices), _KNOWN_SUBCOMMANDS)


if __name__ == "__main__":
    unittest.main()
