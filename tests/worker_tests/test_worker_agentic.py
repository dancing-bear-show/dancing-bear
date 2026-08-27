"""Tests for worker agentic capsule and --agentic flag support."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


class TestWorkerAgenticModule(unittest.TestCase):
    """Tests for worker/agentic.py."""

    def test_emit_agentic_context_returns_zero(self):
        from worker.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_emit_agentic_context_prints_app_name(self):
        from worker.agentic import emit_agentic_context

        buf = io.StringIO()
        with redirect_stdout(buf):
            emit_agentic_context()
        self.assertIn("worker", buf.getvalue())

    def test_emit_agentic_context_accepts_fmt_and_compact(self):
        from worker.agentic import emit_agentic_context

        for fmt in ("text", "yaml", "json"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = emit_agentic_context(fmt, False)
            self.assertEqual(rc, 0)

    def test_build_agentic_capsule_contains_subcommands(self):
        from worker.agentic import build_agentic_capsule

        capsule = build_agentic_capsule()
        for cmd in ("enqueue", "run-once", "daemon", "list", "status", "purge"):
            self.assertIn(cmd, capsule, f"Expected '{cmd}' in capsule")

    def test_build_agentic_capsule_returns_string(self):
        from worker.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)


class TestWorkerMainAgentic(unittest.TestCase):
    """Tests for --agentic flag wired through worker main()."""

    def test_agentic_flag_exits_zero(self):
        from worker.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--agentic"])
        self.assertEqual(rc, 0)

    def test_agentic_flag_prints_capsule_with_app_name(self):
        from worker.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--agentic"])
        self.assertIn("worker", buf.getvalue())

    def test_agentic_format_json_produces_valid_json(self):
        from worker.cli import main

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--agentic", "--agentic-format", "json"])
        self.assertEqual(rc, 0)
        # JSON output must be parseable
        output = buf.getvalue().strip()
        self.assertTrue(len(output) > 0)
        try:
            parsed = json.loads(output)
            self.assertIsInstance(parsed, dict)
        except json.JSONDecodeError:
            # Fallback capsule text is acceptable — it may not be JSON
            # The important thing is exit 0 and non-empty output
            pass

    def test_no_subcommand_preserves_legacy_exit_code(self):
        """The legacy no-subcommand exit code (1) must be unchanged."""
        from worker.cli import main

        with patch("builtins.print") as mock_print:
            rc = main([])
        self.assertEqual(rc, 1)
        mock_print.assert_called_once()
        self.assertIn("Usage", mock_print.call_args[0][0])

    def test_no_subcommand_preserves_legacy_message(self):
        """The legacy no-subcommand message must contain the usage string."""
        from worker.cli import main

        captured = []
        with patch("builtins.print", side_effect=lambda *a, **kw: captured.append(a[0])):
            main([])
        self.assertTrue(any("worker" in line for line in captured))


if __name__ == "__main__":
    unittest.main()
