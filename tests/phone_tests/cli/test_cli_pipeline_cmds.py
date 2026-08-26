"""Tests for phone CLI pipeline command delegation.

Tests that pipeline commands correctly delegate to run_pipeline
with properly constructed request objects from args.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock, patch

from phone.cli.main import (
    cmd_analyze,
    cmd_checklist,
    cmd_export,
    cmd_export_device,
    cmd_iconmap,
    cmd_identity_verify,
    cmd_manifest_from_device,
    cmd_manifest_from_export,
    cmd_manifest_install,
    cmd_plan,
    cmd_prune,
    cmd_unused,
)
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


@dataclass
class PipelineDelegationCase:
    """One cmd_* -> run_pipeline delegation scenario."""

    name: str
    patch_target: str
    command: Callable[[MagicMock], int]
    args: MagicMock
    check_request: Callable[[unittest.TestCase, Any], None]
    assert_called_once: bool = True


CASES: list[PipelineDelegationCase] = [
    PipelineDelegationCase(
        name="export",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_export,
        args=make_export_args(backup="/path/to/backup", out="out/export.yaml"),
        check_request=lambda t, r: (
            t.assertEqual(r.backup, "/path/to/backup"),
            t.assertEqual(r.out_path, Path("out/export.yaml")),
        ),
    ),
    PipelineDelegationCase(
        name="export_device",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_export_device,
        args=make_export_device_args(out="out/device.yaml", udid="test-udid"),
        check_request=lambda t, r: (
            t.assertEqual(r.out_path, Path("out/device.yaml")),
            t.assertEqual(r.udid, "test-udid"),
        ),
    ),
    PipelineDelegationCase(
        name="iconmap",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_iconmap,
        args=make_iconmap_args(out="out/icons.json", udid="test-udid"),
        check_request=lambda t, r: (
            t.assertEqual(r.out_path, Path("out/icons.json")),
            t.assertEqual(r.udid, "test-udid"),
        ),
    ),
    PipelineDelegationCase(
        name="plan",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_plan,
        args=make_plan_args(layout="export.yaml", out="plan.yaml"),
        check_request=lambda t, r: (
            t.assertEqual(r.layout, "export.yaml"),
            t.assertEqual(r.out_path, Path("plan.yaml")),
        ),
    ),
    PipelineDelegationCase(
        name="plan_with_backup_instead_of_layout",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_plan,
        args=make_plan_args(backup="/backup/path", layout=None, out="plan.yaml"),
        check_request=lambda t, r: (
            t.assertEqual(r.backup, "/backup/path"),
            t.assertIsNone(r.layout),
        ),
        assert_called_once=False,
    ),
    PipelineDelegationCase(
        name="checklist",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_checklist,
        args=make_checklist_args(plan="plan.yaml", layout="export.yaml", out="checklist.txt"),
        check_request=lambda t, r: (
            t.assertEqual(r.plan_path, Path("plan.yaml")),
            t.assertEqual(r.layout, "export.yaml"),
            t.assertEqual(r.out_path, Path("checklist.txt")),
        ),
    ),
    PipelineDelegationCase(
        name="unused",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_unused,
        args=make_unused_args(layout="export.yaml", keep="/path/to/keep.txt", limit=30, format="csv"),
        check_request=lambda t, r: (
            t.assertEqual(r.layout, "export.yaml"),
            t.assertEqual(r.keep_path, "/path/to/keep.txt"),
            t.assertEqual(r.limit, 30),
            t.assertEqual(r.format, "csv"),
        ),
    ),
    PipelineDelegationCase(
        name="prune",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_prune,
        args=make_prune_args(layout="export.yaml", mode="delete", out="prune.txt"),
        check_request=lambda t, r: (
            t.assertEqual(r.layout, "export.yaml"),
            t.assertEqual(r.mode, "delete"),
            t.assertEqual(r.out_path, Path("prune.txt")),
        ),
    ),
    PipelineDelegationCase(
        name="analyze",
        patch_target="phone.cli.cmd_layout.run_pipeline",
        command=cmd_analyze,
        args=make_analyze_args(layout="export.yaml", plan="plan.yaml", format="json"),
        check_request=lambda t, r: (
            t.assertEqual(r.layout, "export.yaml"),
            t.assertEqual(r.plan_path, "plan.yaml"),
            t.assertEqual(r.format, "json"),
        ),
    ),
    PipelineDelegationCase(
        name="manifest_from_export",
        patch_target="phone.cli.cmd_profile.run_pipeline",
        command=cmd_manifest_from_export,
        args=make_manifest_from_export_args(export="export.yaml", out="manifest.yaml"),
        check_request=lambda t, r: (
            t.assertEqual(r.export_path, Path("export.yaml")),
            t.assertEqual(r.out_path, Path("manifest.yaml")),
        ),
    ),
    PipelineDelegationCase(
        name="manifest_from_device",
        patch_target="phone.cli.cmd_profile.run_pipeline",
        command=cmd_manifest_from_device,
        args=make_manifest_from_device_args(out="manifest.yaml", udid="test-udid"),
        check_request=lambda t, r: (
            t.assertEqual(r.out_path, Path("manifest.yaml")),
            t.assertEqual(r.udid, "test-udid"),
        ),
    ),
    PipelineDelegationCase(
        name="manifest_install",
        patch_target="phone.cli.cmd_profile.run_pipeline",
        command=cmd_manifest_install,
        args=make_manifest_install_args(manifest="manifest.yaml"),
        check_request=lambda t, r: t.assertEqual(r.manifest_path, Path("manifest.yaml")),
    ),
    PipelineDelegationCase(
        name="identity_verify",
        patch_target="phone.cli.cmd_profile.run_pipeline",
        command=cmd_identity_verify,
        args=make_identity_verify_args(p12="/path/to/cert.p12", udid="test-udid"),
        # device_label is set from udid via os.environ, not directly on request
        check_request=lambda t, r: t.assertEqual(r.p12_path, "/path/to/cert.p12"),
    ),
]


class TestPipelineCommands(unittest.TestCase):
    """Test that pipeline commands delegate to run_pipeline correctly."""

    def test_command_delegates_to_pipeline(self):
        """Each cmd_* builds a request from args and delegates to run_pipeline."""
        for case in CASES:
            with self.subTest(case=case.name):
                with patch(case.patch_target) as mock_run:
                    mock_run.return_value = 0

                    result = case.command(case.args)

                    self.assertEqual(result, 0)
                    if case.assert_called_once:
                        mock_run.assert_called_once()
                    request = mock_run.call_args[0][0]
                    case.check_request(self, request)


if __name__ == "__main__":
    unittest.main()
