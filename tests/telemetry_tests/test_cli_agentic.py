"""Tests for the telemetry Click group's --agentic / --agentic-format / --agentic-compact.

The telemetry CLI is Click-based (not argparse + CLIApp like siblings), so the
agentic flags are implemented as eager options on the group itself. These tests
verify:

* the flags are wired at the group level and exit 0 without needing a subcommand
* text/yaml/json output shapes match the sibling capsule contract
* normal subcommand dispatch is unaffected
* --help still works and now advertises the new flags
"""
from __future__ import annotations

import json
import unittest

from click.testing import CliRunner

from telemetry.agentic import (
    APP_ID,
    PURPOSE,
    build_agentic_capsule,
    build_agentic_capsule_compact,
    build_agentic_json,
)
from telemetry.cli_sessions import main as click_group


class AgenticFlagTests(unittest.TestCase):
    def _runner(self) -> CliRunner:
        # standalone_mode=False turns Click's SystemExit into a return value we
        # can inspect; combined with CliRunner it also captures stdout.
        return CliRunner()

    def test_agentic_flag_exits_zero_without_subcommand(self):
        result = self._runner().invoke(click_group, ["--agentic"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn(f"agentic: {APP_ID}", result.output)
        # Must not be the "Missing command" error surface.
        self.assertNotIn("Missing command", result.output)

    def test_agentic_text_capsule_lists_key_commands(self):
        result = self._runner().invoke(click_group, ["--agentic"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        for cmd in ("live", "stats", "summary", "history", "sessions", "agents", "cost", "otel"):
            self.assertIn(cmd, result.output, msg=f"missing command in capsule: {cmd}")

    def test_agentic_json_is_parseable(self):
        result = self._runner().invoke(click_group, ["--agentic", "--agentic-format", "json"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["app_id"], APP_ID)
        self.assertEqual(payload["purpose"], PURPOSE)
        names = {entry["name"] for entry in payload["commands"]}
        # A few command names that must survive Click introspection.
        for expected in ("live", "stats", "summary", "cost", "otel"):
            self.assertIn(expected, names)

    def test_agentic_json_compact_drops_notes(self):
        result = self._runner().invoke(
            click_group, ["--agentic", "--agentic-format", "json", "--agentic-compact"]
        )
        self.assertEqual(result.exit_code, 0, msg=result.output)
        payload = json.loads(result.output)
        self.assertNotIn("notes", payload)
        # Compact form still lists commands, but drops per-command options.
        self.assertTrue(payload["commands"])
        self.assertNotIn("options", payload["commands"][0])

    def test_agentic_yaml_shape_matches_text(self):
        # text and yaml share the same hand-authored body — YAML-valid by construction.
        text = self._runner().invoke(click_group, ["--agentic", "--agentic-format", "text"])
        yaml_out = self._runner().invoke(click_group, ["--agentic", "--agentic-format", "yaml"])
        self.assertEqual(text.exit_code, 0)
        self.assertEqual(yaml_out.exit_code, 0)
        self.assertEqual(text.output, yaml_out.output)

    def test_agentic_compact_text_drops_notes(self):
        result = self._runner().invoke(click_group, ["--agentic", "--agentic-compact"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn(f"agentic: {APP_ID}", result.output)
        self.assertNotIn("notes:", result.output)


class HelpAndDispatchTests(unittest.TestCase):
    def test_help_still_works_and_shows_agentic_flags(self):
        result = CliRunner().invoke(click_group, ["--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("--agentic", result.output)
        self.assertIn("--agentic-format", result.output)
        self.assertIn("--agentic-compact", result.output)
        # The command list must remain visible.
        self.assertIn("sessions", result.output)
        self.assertIn("cost", result.output)

    def test_bare_invocation_preserves_legacy_exit_two(self):
        # Original behavior: Click's default `no subcommand → help + exit 2`.
        # We use invoke_without_command=True to accept --agentic, but the
        # subcommand-less path must still exit non-zero for scripts that rely
        # on it.
        result = CliRunner().invoke(click_group, [])
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Usage:", result.output)

    def test_cost_subcommand_still_dispatches(self):
        # A cheap subcommand: `cost --help` proves the group still wires
        # subcommands after adding the agentic options.
        result = CliRunner().invoke(click_group, ["cost", "--help"])
        self.assertEqual(result.exit_code, 0, msg=result.output)
        self.assertIn("Per-agent or per-day cost breakdown", result.output)


class CapsuleContentTests(unittest.TestCase):
    """Direct tests on the agentic module — no Click involvement."""

    def test_text_capsule_starts_with_agentic_header(self):
        body = build_agentic_capsule()
        self.assertTrue(body.startswith(f"agentic: {APP_ID}"))
        self.assertIn("purpose:", body)
        self.assertIn("commands:", body)
        self.assertIn("notes:", body)

    def test_compact_capsule_omits_notes_section(self):
        body = build_agentic_capsule_compact()
        self.assertTrue(body.startswith(f"agentic: {APP_ID}"))
        self.assertIn("commands:", body)
        self.assertNotIn("notes:", body)

    def test_json_capsule_reflects_registered_commands(self):
        payload = build_agentic_json(compact=False)
        names = {entry["name"] for entry in payload["commands"]}
        # These are all defined in telemetry.cli_sessions; if any is renamed,
        # the JSON schema must reflect it — this test forces the update.
        for expected in ("agents", "cost", "cost-breakdown", "history", "live",
                         "otel", "parse-transcripts", "rules", "sessions",
                         "stats", "summary"):
            self.assertIn(expected, names, msg=f"command missing from JSON schema: {expected}")


if __name__ == "__main__":
    unittest.main()
