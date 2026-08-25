"""Tests for the sheets agentic capsule.

The capsule is what an LLM agent reads to discover this CLI, so its command
strings must stay in step with the real parser -- a capsule advertising a flag
that does not exist sends an agent down a dead end.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from sheets.agentic import build_agentic_capsule, emit_agentic_context


class TestBuildAgenticCapsule(unittest.TestCase):
    def test_names_the_app(self) -> None:
        self.assertIn("agentic: sheets", build_agentic_capsule())

    def test_documents_both_subcommands(self) -> None:
        capsule = build_agentic_capsule()
        self.assertIn("generate", capsule)
        self.assertIn("validate", capsule)

    def test_advertised_commands_match_the_real_parser(self) -> None:
        # Guards against capsule drift: every subcommand the capsule names must
        # actually exist on the built parser.
        import argparse

        from sheets.cli import app

        parser = app.build_parser()
        registered: set[str] = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices)

        capsule = build_agentic_capsule()
        for command in ("generate", "validate"):
            with self.subTest(command=command):
                self.assertIn(f"- {command}:", capsule)
                self.assertIn(command, registered)


class TestEmitAgenticContext(unittest.TestCase):
    def test_returns_zero_and_prints_capsule(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: sheets", buf.getvalue())

    def test_format_and_compact_args_are_accepted(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context("json", True)
        self.assertEqual(rc, 0)
        self.assertTrue(buf.getvalue().strip())
