"""Tests for the telemetry CLI --agentic / --agentic-format / --agentic-compact.

The telemetry CLI is now argparse-based (CLIApp). These tests verify:

* --agentic exits 0 and announces agentic: telemetry
* text/yaml/json output shapes match the sibling capsule contract
* normal subcommand dispatch is unaffected
* --help still works and advertises the new flags
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest

from telemetry.agentic import (
    APP_ID,
    PURPOSE,
    build_agentic_capsule,
    build_agentic_capsule_compact,
)
from telemetry.cli_sessions import main


def _run(argv: list[str]) -> tuple[int, str]:
    """Invoke main(argv) and return (rc, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


class AgenticFlagTests(unittest.TestCase):
    def test_agentic_flag_exits_zero_without_subcommand(self):
        rc, out = _run(["--agentic"])
        self.assertEqual(rc, 0, msg=out)
        self.assertIn(f"agentic: {APP_ID}", out)

    def test_agentic_text_capsule_lists_key_commands(self):
        rc, out = _run(["--agentic"])
        self.assertEqual(rc, 0, msg=out)
        for cmd in ("live", "stats", "summary", "history", "sessions", "agents", "cost", "otel"):
            self.assertIn(cmd, out, msg=f"missing command in capsule: {cmd}")

    def test_agentic_json_is_parseable(self):
        rc, out = _run(["--agentic", "--agentic-format", "json"])
        self.assertEqual(rc, 0, msg=out)
        payload = json.loads(out)
        # argparse-based schema uses these keys
        self.assertIn("prog", payload)
        self.assertIn("subcommands", payload)

    def test_agentic_json_has_expected_schema_keys(self):
        rc, out = _run(["--agentic", "--agentic-format", "json"])
        self.assertEqual(rc, 0, msg=out)
        payload = json.loads(out)
        expected_keys = {"prog", "description", "usage", "options", "subcommands", "epilog"}
        self.assertEqual(expected_keys, set(payload))

    def test_agentic_json_compact_is_smaller(self):
        _, full = _run(["--agentic", "--agentic-format", "json"])
        _, compact = _run(["--agentic", "--agentic-format", "json", "--agentic-compact"])
        self.assertLess(len(compact.encode("utf-8")), len(full.encode("utf-8")))

    def test_agentic_yaml_shape_matches_text(self):
        # text and yaml share the same hand-authored body
        _, text_out = _run(["--agentic", "--agentic-format", "text"])
        _, yaml_out = _run(["--agentic", "--agentic-format", "yaml"])
        self.assertEqual(text_out, yaml_out)

    def test_agentic_compact_text_drops_notes(self):
        rc, out = _run(["--agentic", "--agentic-compact"])
        self.assertEqual(rc, 0, msg=out)
        self.assertIn(f"agentic: {APP_ID}", out)
        self.assertNotIn("notes:", out)


class HelpAndDispatchTests(unittest.TestCase):
    def test_help_still_works_and_shows_agentic_flags(self):
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main(["--help"])
        except SystemExit as e:  # NOSONAR - argparse --help exits by design; re-raising would defeat the assertion
            self.assertEqual(e.code, 0)
        out = buf.getvalue()
        self.assertIn("--agentic", out)
        self.assertIn("--agentic-format", out)
        self.assertIn("--agentic-compact", out)
        self.assertIn("sessions", out)
        self.assertIn("cost", out)

    def test_bare_invocation_preserves_legacy_exit_two(self):
        rc, _ = _run([])
        self.assertEqual(rc, 2)

    def test_cost_alias_dispatches(self):
        # cost is an alias for cost-breakdown; --help proves it is wired
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                main(["cost", "--help"])
        except SystemExit as e:  # NOSONAR - argparse --help exits by design; re-raising would defeat the assertion
            self.assertEqual(e.code, 0)
        out = buf.getvalue()
        self.assertIn("cost breakdown", out.lower())


class CapsuleContentTests(unittest.TestCase):
    """Direct tests on the agentic module — no CLI involvement."""

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

    def test_purpose_is_set(self):
        self.assertIn("telemetry", PURPOSE.lower())


if __name__ == "__main__":
    unittest.main()
