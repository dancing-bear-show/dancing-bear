"""Tests for schedule/agentic.py flow map branches and capsule sections."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


def _make_path_mock(true_paths: set):
    """Return a function that returns True only for the given paths."""
    def _exists(path):
        return tuple(path) in true_paths
    return _exists


class TestScheduleFlowMap(unittest.TestCase):
    def test_plan_flow(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock({("plan",)})):
            result = mod._flow_map()
        self.assertIn("Plan", result)
        self.assertIn("schedule-assistant plan", result)

    def test_apply_flow(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock({("apply",)})):
            result = mod._flow_map()
        self.assertIn("Apply", result)
        self.assertIn("dry-run", result)
        self.assertIn("apply --plan", result)

    def test_verify_flow(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock({("verify",)})):
            result = mod._flow_map()
        self.assertIn("Verify", result)
        self.assertIn("verify --plan", result)

    def test_sync_flow(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock({("sync",)})):
            result = mod._flow_map()
        self.assertIn("Sync", result)
        self.assertIn("sync --plan", result)

    def test_export_flow(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock({("export",)})):
            result = mod._flow_map()
        self.assertIn("Export", result)
        self.assertIn("export --calendar", result)

    def test_compress_flow(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock({("compress",)})):
            result = mod._flow_map()
        self.assertIn("Compress", result)
        self.assertIn("compress --in", result)

    def test_all_flows(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=True):
            result = mod._flow_map()
        self.assertIn("Plan", result)
        self.assertIn("Apply", result)
        self.assertIn("Verify", result)
        self.assertIn("Sync", result)
        self.assertIn("Export", result)
        self.assertIn("Compress", result)

    def test_empty_flow_map(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=False):
            result = mod._flow_map()
        self.assertEqual(result, "")


class TestScheduleBuildAgenticCapsule(unittest.TestCase):
    def test_capsule_non_empty(self):
        from schedule.agentic import build_agentic_capsule
        cap = build_agentic_capsule()
        self.assertIsInstance(cap, str)
        self.assertGreater(len(cap), 0)

    def test_capsule_with_tree_and_flows(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=True), \
             patch.object(mod, "_cli_tree", return_value="cli-tree-content"):
            cap = mod.build_agentic_capsule()
        self.assertIn("cli-tree-content", cap)
        self.assertIn("Plan", cap)

    def test_capsule_no_tree_no_flows(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=False), \
             patch.object(mod, "_cli_tree", return_value=""):
            cap = mod.build_agentic_capsule()
        self.assertIsInstance(cap, str)
        self.assertGreater(len(cap), 0)

    def test_capsule_mentions_schedule(self):
        from schedule.agentic import build_agentic_capsule
        cap = build_agentic_capsule()
        self.assertIn("schedule", cap.lower())


class TestScheduleBuildDomainMap(unittest.TestCase):
    def test_domain_map_non_empty(self):
        from schedule.agentic import build_domain_map
        dm = build_domain_map()
        self.assertIsInstance(dm, str)
        self.assertGreater(len(dm), 0)

    def test_domain_map_has_top_level(self):
        from schedule.agentic import build_domain_map
        dm = build_domain_map()
        self.assertIn("Top-Level", dm)

    def test_domain_map_with_tree_and_flows(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=True), \
             patch.object(mod, "_cli_tree", return_value="cli-tree-content"):
            dm = mod.build_domain_map()
        self.assertIn("cli-tree-content", dm)
        self.assertIn("Plan", dm)

    def test_domain_map_no_tree_no_flows(self):
        from schedule import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=False), \
             patch.object(mod, "_cli_tree", return_value=""):
            dm = mod.build_domain_map()
        self.assertIn("Top-Level", dm)


class TestScheduleEmitAgenticContext(unittest.TestCase):
    def test_emit_returns_zero(self):
        from schedule.agentic import emit_agentic_context
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)
        self.assertGreater(len(buf.getvalue()), 0)

    def test_emit_accepts_fmt_compact(self):
        from schedule.agentic import emit_agentic_context
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = emit_agentic_context(_fmt="yaml", _compact=True)
        self.assertEqual(rc, 0)


class TestScheduleCliTree(unittest.TestCase):
    def test_cli_tree_returns_string(self):
        from schedule.agentic import _cli_tree
        result = _cli_tree()
        self.assertIsInstance(result, str)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
