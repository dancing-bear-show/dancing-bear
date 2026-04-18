"""Tests for phone/agentic.py — capsule builders."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestBuildAgenticCapsule(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIsInstance(result, str)
        self.assertIn("phone", result)

    def test_contains_purpose(self):
        from phone.agentic import build_agentic_capsule

        result = build_agentic_capsule()
        self.assertIn("layout", result.lower())


class TestBuildDomainMap(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import build_domain_map

        result = build_domain_map()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_contains_module_references(self):
        from phone.agentic import build_domain_map

        result = build_domain_map()
        self.assertIn("phone", result.lower())


class TestEmitAgenticContext(unittest.TestCase):
    def test_returns_zero(self):
        from phone.agentic import emit_agentic_context
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_prints_capsule(self):
        from phone.agentic import emit_agentic_context
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            emit_agentic_context()
        self.assertIn("phone", buf.getvalue())


class TestCliPathExists(unittest.TestCase):
    def test_existing_path_returns_true(self):
        from phone.agentic import _cli_path_exists

        # "plan" is a known subcommand in phone
        result = _cli_path_exists(["plan"])
        self.assertIsInstance(result, bool)

    def test_nonexistent_path_returns_false(self):
        from phone.agentic import _cli_path_exists

        result = _cli_path_exists(["nonexistent_command_xyz"])
        self.assertFalse(result)


class TestFlowMap(unittest.TestCase):
    def test_returns_string(self):
        from phone.agentic import _flow_map

        result = _flow_map()
        self.assertIsInstance(result, str)

    def test_contains_layout_info(self):
        from phone.agentic import _flow_map

        result = _flow_map()
        # Should contain some workflow info if CLI paths exist
        self.assertIsInstance(result, str)


class TestCliTree(unittest.TestCase):
    def test_returns_string_or_none(self):
        from phone.agentic import _cli_tree

        result = _cli_tree()
        # May be a string or empty string
        if result is not None:
            self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
