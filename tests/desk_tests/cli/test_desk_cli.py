"""Tests for desk/cli.py command functions and helpers."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import capture_stdout, make_mock_envelope


class TestStarterRulesYaml(unittest.TestCase):
    def test_contains_version(self):
        from desk.cli import _starter_rules_yaml
        result = _starter_rules_yaml()
        self.assertIn("version: 1", result)

    def test_contains_rules_key(self):
        from desk.cli import _starter_rules_yaml
        result = _starter_rules_yaml()
        self.assertIn("rules:", result)

    def test_contains_example_rule(self):
        from desk.cli import _starter_rules_yaml
        result = _starter_rules_yaml()
        self.assertIn("move_to:", result)


class TestCmdScan(unittest.TestCase):
    def test_scan_success_returns_0(self):
        from desk.cli import cmd_scan

        args = MagicMock()
        args.paths = ["/tmp/fake"]  # nosec B108 - test-only temp path, not a security concern
        args.min_size = "50MB"
        args.older_than = None
        args.duplicates = False
        args.top_dirs = 10
        args.out = None

        envelope = make_mock_envelope(ok=True, result={"files": []})

        with patch("desk.cli.ScanProcessor") as MockProc:
            with patch("desk.cli.ScanRequestConsumer") as MockConsumer:
                with patch("desk.cli.ReportProducer") as MockProducer:
                    MockProc.return_value.process.return_value = envelope
                    MockConsumer.return_value.consume.return_value = MagicMock()
                    MockProducer.return_value.produce.return_value = None

                    rc = cmd_scan(args)

        self.assertEqual(rc, 0)

    def test_scan_failure_returns_1(self):
        from desk.cli import cmd_scan

        args = MagicMock()
        args.paths = ["/tmp/fake"]  # nosec B108 - test-only temp path, not a security concern
        args.min_size = "50MB"
        args.older_than = None
        args.duplicates = False
        args.top_dirs = 10
        args.out = None

        envelope = make_mock_envelope(ok=False, error="scan failed")

        with patch("desk.cli.ScanProcessor") as MockProc:
            with patch("desk.cli.ScanRequestConsumer") as MockConsumer:
                with patch("desk.cli.ReportProducer") as MockProducer:
                    MockProc.return_value.process.return_value = envelope
                    MockConsumer.return_value.consume.return_value = MagicMock()
                    MockProducer.return_value.produce.return_value = None

                    rc = cmd_scan(args)

        self.assertEqual(rc, 1)


class TestCmdPlan(unittest.TestCase):
    def test_plan_success_returns_0(self):
        from desk.cli import cmd_plan

        args = MagicMock()
        args.config = "/fake/rules.yaml"
        args.out = None

        envelope = make_mock_envelope(ok=True, result={"plan": []})

        with patch("desk.cli.PlanProcessor") as MockProc:
            with patch("desk.cli.PlanRequestConsumer") as MockConsumer:
                with patch("desk.cli.ReportProducer") as MockProducer:
                    MockProc.return_value.process.return_value = envelope
                    MockConsumer.return_value.consume.return_value = MagicMock()
                    MockProducer.return_value.produce.return_value = None

                    rc = cmd_plan(args)

        self.assertEqual(rc, 0)

    def test_plan_failure_returns_1(self):
        from desk.cli import cmd_plan

        args = MagicMock()
        args.config = "/fake/rules.yaml"
        args.out = None

        envelope = make_mock_envelope(ok=False, error="plan failed")

        with patch("desk.cli.PlanProcessor") as MockProc:
            with patch("desk.cli.PlanRequestConsumer") as MockConsumer:
                with patch("desk.cli.ReportProducer") as MockProducer:
                    MockProc.return_value.process.return_value = envelope
                    MockConsumer.return_value.consume.return_value = MagicMock()
                    MockProducer.return_value.produce.return_value = None

                    rc = cmd_plan(args)

        self.assertEqual(rc, 1)


class TestCmdApply(unittest.TestCase):
    def test_apply_success_returns_0(self):
        from desk.cli import cmd_apply

        args = MagicMock()
        args.plan = "/fake/plan.yaml"
        args.dry_run = True

        envelope = make_mock_envelope(ok=True, result={"actions": []})

        with patch("desk.cli.ApplyProcessor") as MockProc:
            with patch("desk.pipeline.ApplyRequestConsumer") as MockConsumer:
                with patch("desk.cli.ApplyResultProducer") as MockProducer:
                    MockProc.return_value.process.return_value = envelope
                    MockConsumer.return_value.consume.return_value = MagicMock()
                    MockProducer.return_value.produce.return_value = None

                    rc = cmd_apply(args)

        self.assertEqual(rc, 0)

    def test_apply_failure_returns_1(self):
        from desk.cli import cmd_apply

        args = MagicMock()
        args.plan = "/fake/plan.yaml"
        args.dry_run = False

        envelope = make_mock_envelope(ok=False, error="apply failed")

        with patch("desk.cli.ApplyProcessor") as MockProc:
            with patch("desk.pipeline.ApplyRequestConsumer") as MockConsumer:
                with patch("desk.cli.ApplyResultProducer") as MockProducer:
                    MockProc.return_value.process.return_value = envelope
                    MockConsumer.return_value.consume.return_value = MagicMock()
                    MockProducer.return_value.produce.return_value = None

                    rc = cmd_apply(args)

        self.assertEqual(rc, 1)


class TestCmdRulesExport(unittest.TestCase):
    def test_exports_starter_yaml(self):
        from desk.cli import cmd_rules_export

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "rules.yaml")
            args = MagicMock()
            args.out = out_path

            with capture_stdout():
                rc = cmd_rules_export(args)

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_path))
            content = Path(out_path).read_text()
            self.assertIn("version: 1", content)

    def test_creates_missing_directory(self):
        from desk.cli import cmd_rules_export

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "subdir", "rules.yaml")
            args = MagicMock()
            args.out = out_path

            with capture_stdout():
                rc = cmd_rules_export(args)

            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out_path))

    def test_prints_confirmation(self):
        from desk.cli import cmd_rules_export

        with tempfile.TemporaryDirectory() as td:
            out_path = os.path.join(td, "rules.yaml")
            args = MagicMock()
            args.out = out_path

            with capture_stdout() as buf:
                cmd_rules_export(args)

            self.assertIn("Wrote starter rules", buf.getvalue())


class TestEmitAgentic(unittest.TestCase):
    def test_emit_agentic_returns_0(self):
        from desk.cli import _emit_agentic
        with capture_stdout():
            rc = _emit_agentic("yaml", False)
        self.assertEqual(rc, 0)

    def test_emit_agentic_compact_returns_0(self):
        from desk.cli import _emit_agentic
        with capture_stdout():
            rc = _emit_agentic("yaml", True)
        self.assertEqual(rc, 0)


class TestPathsDefault(unittest.TestCase):
    def test_returns_list_with_downloads_and_desktop(self):
        from desk.cli import _paths_default
        paths = _paths_default()
        self.assertIsInstance(paths, list)
        self.assertEqual(len(paths), 2)
        downloads = any("Downloads" in p for p in paths)
        desktop = any("Desktop" in p for p in paths)
        self.assertTrue(downloads)
        self.assertTrue(desktop)


if __name__ == "__main__":
    unittest.main()
