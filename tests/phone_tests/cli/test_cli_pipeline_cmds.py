"""Tests for phone CLI pipeline command delegation.

Tests that pipeline commands correctly delegate to run_pipeline
with properly constructed request objects from args.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tests.phone_tests.cli.fixtures import (
    make_analyze_args,
    make_checklist_args,
    make_export_args,
    make_export_device_args,
    make_iconmap_args,
    make_identity_verify_args,
    make_manifest_from_device_args,
    make_manifest_from_export_args,
    make_manifest_install_args,
    make_plan_args,
    make_prune_args,
    make_unused_args,
)


class TestPipelineCommands(unittest.TestCase):
    """Test that pipeline commands delegate to run_pipeline correctly."""

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_export_delegates_to_pipeline(self, mock_run):
        """Test cmd_export delegates to run_pipeline."""
        from phone.cli.main import cmd_export

        mock_run.return_value = 0
        args = make_export_args(backup="/path/to/backup", out="out/export.yaml")

        result = cmd_export(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.backup, "/path/to/backup")
        self.assertEqual(request.out_path, Path("out/export.yaml"))

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_export_device_delegates_to_pipeline(self, mock_run):
        """Test cmd_export_device delegates to run_pipeline."""
        from phone.cli.main import cmd_export_device

        mock_run.return_value = 0
        args = make_export_device_args(out="out/device.yaml", udid="test-udid")

        result = cmd_export_device(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.out_path, Path("out/device.yaml"))
        self.assertEqual(request.udid, "test-udid")

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_iconmap_delegates_to_pipeline(self, mock_run):
        """Test cmd_iconmap delegates to run_pipeline."""
        from phone.cli.main import cmd_iconmap

        mock_run.return_value = 0
        args = make_iconmap_args(out="out/icons.json", udid="test-udid")

        result = cmd_iconmap(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.out_path, Path("out/icons.json"))
        self.assertEqual(request.udid, "test-udid")

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_plan_delegates_to_pipeline(self, mock_run):
        """Test cmd_plan delegates to run_pipeline."""
        from phone.cli.main import cmd_plan

        mock_run.return_value = 0
        args = make_plan_args(layout="export.yaml", out="plan.yaml")

        result = cmd_plan(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.layout, "export.yaml")
        self.assertEqual(request.out_path, Path("plan.yaml"))

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_plan_with_backup_instead_of_layout(self, mock_run):
        """Test cmd_plan accepts backup instead of layout."""
        from phone.cli.main import cmd_plan

        mock_run.return_value = 0
        args = make_plan_args(backup="/backup/path", layout=None, out="plan.yaml")

        result = cmd_plan(args)

        self.assertEqual(result, 0)
        request = mock_run.call_args[0][0]
        self.assertEqual(request.backup, "/backup/path")
        self.assertIsNone(request.layout)

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_checklist_delegates_to_pipeline(self, mock_run):
        """Test cmd_checklist delegates to run_pipeline."""
        from phone.cli.main import cmd_checklist

        mock_run.return_value = 0
        args = make_checklist_args(plan="plan.yaml", layout="export.yaml", out="checklist.txt")

        result = cmd_checklist(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.plan_path, Path("plan.yaml"))
        self.assertEqual(request.layout, "export.yaml")
        self.assertEqual(request.out_path, Path("checklist.txt"))

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_unused_delegates_to_pipeline(self, mock_run):
        """Test cmd_unused delegates to run_pipeline."""
        from phone.cli.main import cmd_unused

        mock_run.return_value = 0
        args = make_unused_args(layout="export.yaml", keep="/path/to/keep.txt", limit=30, format="csv")

        result = cmd_unused(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.layout, "export.yaml")
        self.assertEqual(request.keep_path, "/path/to/keep.txt")
        self.assertEqual(request.limit, 30)
        self.assertEqual(request.format, "csv")

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_prune_delegates_to_pipeline(self, mock_run):
        """Test cmd_prune delegates to run_pipeline."""
        from phone.cli.main import cmd_prune

        mock_run.return_value = 0
        args = make_prune_args(layout="export.yaml", mode="delete", out="prune.txt")

        result = cmd_prune(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.layout, "export.yaml")
        self.assertEqual(request.mode, "delete")
        self.assertEqual(request.out_path, Path("prune.txt"))

    @patch("phone.cli.cmd_layout.run_pipeline")
    def test_analyze_delegates_to_pipeline(self, mock_run):
        """Test cmd_analyze delegates to run_pipeline."""
        from phone.cli.main import cmd_analyze

        mock_run.return_value = 0
        args = make_analyze_args(layout="export.yaml", plan="plan.yaml", format="json")

        result = cmd_analyze(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.layout, "export.yaml")
        self.assertEqual(request.plan_path, "plan.yaml")
        self.assertEqual(request.format, "json")

    @patch("phone.cli.cmd_profile.run_pipeline")
    def test_manifest_from_export_delegates_to_pipeline(self, mock_run):
        """Test cmd_manifest_from_export delegates to run_pipeline."""
        from phone.cli.main import cmd_manifest_from_export

        mock_run.return_value = 0
        args = make_manifest_from_export_args(export="export.yaml", out="manifest.yaml")

        result = cmd_manifest_from_export(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.export_path, Path("export.yaml"))
        self.assertEqual(request.out_path, Path("manifest.yaml"))

    @patch("phone.cli.cmd_profile.run_pipeline")
    def test_manifest_from_device_delegates_to_pipeline(self, mock_run):
        """Test cmd_manifest_from_device delegates to run_pipeline."""
        from phone.cli.main import cmd_manifest_from_device

        mock_run.return_value = 0
        args = make_manifest_from_device_args(out="manifest.yaml", udid="test-udid")

        result = cmd_manifest_from_device(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.out_path, Path("manifest.yaml"))
        self.assertEqual(request.udid, "test-udid")

    @patch("phone.cli.cmd_profile.run_pipeline")
    def test_manifest_install_delegates_to_pipeline(self, mock_run):
        """Test cmd_manifest_install delegates to run_pipeline."""
        from phone.cli.main import cmd_manifest_install

        mock_run.return_value = 0
        args = make_manifest_install_args(manifest="manifest.yaml")

        result = cmd_manifest_install(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.manifest_path, Path("manifest.yaml"))

    @patch("phone.cli.cmd_profile.run_pipeline")
    def test_identity_verify_delegates_to_pipeline(self, mock_run):
        """Test cmd_identity_verify delegates to run_pipeline."""
        from phone.cli.main import cmd_identity_verify

        mock_run.return_value = 0
        args = make_identity_verify_args(p12="/path/to/cert.p12", udid="test-udid")

        result = cmd_identity_verify(args)

        self.assertEqual(result, 0)
        mock_run.assert_called_once()
        request = mock_run.call_args[0][0]
        self.assertEqual(request.p12_path, "/path/to/cert.p12")
        # Note: device_label is set from udid via os.environ, not directly on request


if __name__ == "__main__":
    unittest.main()
