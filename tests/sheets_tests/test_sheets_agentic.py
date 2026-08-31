"""Tests for the sheets agentic capsule.

Adopts AgenticBuilderContractMixin for the shared builder contract
(build_agentic_capsule / emit_agentic_context). sheets hand-writes its capsule
(no build_domain_map, no CLI tree), so EXPECT_DOMAIN_MAP and EXPECT_CLI_TREE
are both False.

The CLI --agentic surface is covered by test_sheets_agentic_cli.py via
AgenticCLIContractMixin.

The capsule is what an LLM agent reads to discover this CLI, so its command
strings must stay in step with the real parser -- a capsule advertising a flag
that does not exist sends an agent down a dead end.
"""

from __future__ import annotations

import unittest

from tests.agentic_builder_contract import AgenticBuilderContractMixin
from sheets.agentic import build_agentic_capsule


class TestSheetsAgenticBuilder(AgenticBuilderContractMixin, unittest.TestCase):
    """The shared agentic builder contract."""

    MODULE_PATH = "sheets.agentic"
    APP_ID = "sheets"
    EXPECT_CLI_TREE = False
    EXPECT_DOMAIN_MAP = False


class TestSheetsCapsuleContent(unittest.TestCase):
    """sheets-specific capsule content not covered by the shared contract."""

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
