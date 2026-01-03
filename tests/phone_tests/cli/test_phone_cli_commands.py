"""Tests for phone CLI command functions.

Tests the refactored phone CLI commands to ensure proper delegation
to pipeline helpers and correct request construction from args.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from tests.phone_tests.cli.fixtures import (
    make_analyze_args,
    make_auto_folders_args,
    make_checklist_args,
    make_export_args,
    make_export_device_args,
    make_iconmap_args,
    make_identity_verify_args,
    make_manifest_build_args,
    make_manifest_create_args,
    make_manifest_from_device_args,
    make_manifest_from_export_args,
    make_manifest_install_args,
    make_plan_args,
    make_profile_build_args,
    make_prune_args,
    make_unused_args,
)
from tests.phone_tests.fixtures import make_mock_manifest, make_mock_plan


class TestPipelineCommands(unittest.TestCase):
    """Test that pipeline commands delegate to run_pipeline correctly."""

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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

    @patch("phone.cli.main.run_pipeline")
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


class TestInlineCommandHelpers(unittest.TestCase):
    """Test helper functions extracted from inline commands."""

    def test_parse_keep_list_splits_comma_separated(self):
        """Test _parse_keep_list splits comma-separated bundle IDs."""
        from phone.cli.main import _parse_keep_list

        result = _parse_keep_list("com.app1,com.app2,com.app3")

        self.assertEqual(result, ["com.app1", "com.app2", "com.app3"])

    def test_parse_keep_list_strips_whitespace(self):
        """Test _parse_keep_list strips whitespace around entries."""
        from phone.cli.main import _parse_keep_list

        result = _parse_keep_list("com.app1, com.app2 ,  com.app3  ")

        self.assertEqual(result, ["com.app1", "com.app2", "com.app3"])

    def test_parse_keep_list_filters_empty_entries(self):
        """Test _parse_keep_list filters out empty entries."""
        from phone.cli.main import _parse_keep_list

        result = _parse_keep_list("com.app1,,com.app2,  ,com.app3")

        self.assertEqual(result, ["com.app1", "com.app2", "com.app3"])

    def test_parse_keep_list_empty_string_returns_empty_list(self):
        """Test _parse_keep_list returns empty list for empty string."""
        from phone.cli.main import _parse_keep_list

        result = _parse_keep_list("")

        self.assertEqual(result, [])

    def test_update_plan_with_folders_adds_folders(self):
        """Test _update_plan_with_folders adds folders to plan."""
        from phone.cli.main import _update_plan_with_folders

        plan = {"pages": {}}
        folders = {"Work": ["com.app1"], "Utils": ["com.app2"]}

        result = _update_plan_with_folders(plan, folders, start_page=2, per_page=12)

        self.assertEqual(result["folders"], folders)
        self.assertIn(2, result["pages"])

    def test_update_plan_with_folders_clears_pages_from_start(self):
        """Test _update_plan_with_folders clears pages >= start_page."""
        from phone.cli.main import _update_plan_with_folders

        plan = {"pages": {1: ["old"], 2: ["cleared"], 3: ["also_cleared"]}}
        folders = {"Work": ["com.app1"]}

        result = _update_plan_with_folders(plan, folders, start_page=2, per_page=12)

        self.assertIn(1, result["pages"])  # Page 1 preserved
        self.assertNotIn("old", result["pages"].get(2, []))  # Page 2 replaced

    def test_update_plan_with_folders_distributes_across_pages(self):
        """Test _update_plan_with_folders distributes folders across pages."""
        from phone.cli.main import _update_plan_with_folders

        plan = {"pages": {}}
        # Create exactly 15 folders with non-empty apps (empty folders are filtered)
        folders = {f"Folder{i:02d}": ["app"] for i in range(15)}  # 15 folders

        result = _update_plan_with_folders(plan, folders, start_page=2, per_page=12)

        # With per_page=12 and 15 folders, should have 2 pages
        # Page 2 should have 12 folders, page 3 should have 3 folders
        self.assertIn(2, result["pages"])
        self.assertIn(3, result["pages"])
        # distribute_folders_across_pages returns folder names as items
        self.assertGreater(len(result["pages"][2]), 0)
        self.assertGreater(len(result["pages"][3]), 0)

    def test_build_all_apps_folder_config_returns_none_when_not_requested(self):
        """Test _build_all_apps_folder_config returns None when not needed."""
        from phone.cli.main import _build_all_apps_folder_config

        args = MagicMock()
        args.all_apps_folder_name = None
        args.all_apps_folder_page = None

        result = _build_all_apps_folder_config(args, layout_export={"pages": {1: []}})

        self.assertIsNone(result)

    def test_build_all_apps_folder_config_raises_without_layout(self):
        """Test _build_all_apps_folder_config raises ValueError without layout."""
        from phone.cli.main import _build_all_apps_folder_config

        args = MagicMock()
        args.all_apps_folder_name = "All Apps"
        args.all_apps_folder_page = None

        with self.assertRaises(ValueError) as ctx:
            _build_all_apps_folder_config(args, layout_export=None)

        self.assertIn("requires --layout", str(ctx.exception))

    def test_build_all_apps_folder_config_builds_folder_dict(self):
        """Test _build_all_apps_folder_config builds folder config."""
        from phone.cli.main import _build_all_apps_folder_config

        args = MagicMock()
        args.all_apps_folder_name = "All Apps"
        args.all_apps_folder_page = 5

        result = _build_all_apps_folder_config(args, layout_export={"pages": {1: []}})

        self.assertEqual(result["name"], "All Apps")
        self.assertEqual(result["page"], 5)

    @patch("phone.cli.main.Path")
    def test_write_mobileconfig_creates_parent_dirs(self, mock_path_cls):
        """Test _write_mobileconfig creates parent directories."""
        from phone.cli.main import _write_mobileconfig

        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_path.open = MagicMock(return_value=mock_open()())
        mock_path_cls.return_value = mock_path

        with patch("plistlib.dump"):
            _write_mobileconfig({"test": "data"}, mock_path)

        mock_path.parent.mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_build_manifest_dict_includes_plan(self):
        """Test _build_manifest_dict includes plan in manifest."""
        from phone.cli.main import _build_manifest_dict

        plan = make_mock_plan()
        args = make_manifest_create_args(from_plan="plan.yaml")

        result = _build_manifest_dict(plan, args)

        self.assertEqual(result["plan"], plan)
        self.assertIn("meta", result)
        self.assertIn("device", result)
        self.assertIn("profile", result)

    def test_build_manifest_dict_includes_layout_path_when_provided(self):
        """Test _build_manifest_dict includes layout_export_path when --layout given."""
        from phone.cli.main import _build_manifest_dict

        plan = make_mock_plan()
        args = make_manifest_create_args(layout="export.yaml")

        result = _build_manifest_dict(plan, args)

        self.assertIn("layout_export_path", result)
        self.assertEqual(result["layout_export_path"], str(Path("export.yaml")))

    def test_build_manifest_dict_omits_layout_path_when_not_provided(self):
        """Test _build_manifest_dict omits layout_export_path when --layout not given."""
        from phone.cli.main import _build_manifest_dict

        plan = make_mock_plan()
        args = make_manifest_create_args(layout=None)

        result = _build_manifest_dict(plan, args)

        self.assertNotIn("layout_export_path", result)

    def test_extract_manifest_profile_config_extracts_plan(self):
        """Test _extract_manifest_profile_config extracts plan from manifest."""
        from phone.cli.main import _extract_manifest_profile_config

        manifest = make_mock_manifest()

        plan, layout, profile = _extract_manifest_profile_config(manifest)

        self.assertEqual(plan, manifest["plan"])
        self.assertIsNone(layout)  # No layout_export_path in default manifest
        self.assertEqual(profile, manifest["profile"])

    def test_extract_manifest_profile_config_raises_on_missing_plan(self):
        """Test _extract_manifest_profile_config raises ValueError for invalid manifest."""
        from phone.cli.main import _extract_manifest_profile_config

        invalid_manifest = {"meta": {}, "device": {}}  # Missing 'plan'

        with self.assertRaises(ValueError) as ctx:
            _extract_manifest_profile_config(invalid_manifest)

        self.assertIn("missing 'plan'", str(ctx.exception))

    @patch("phone.cli.main.read_yaml")
    def test_extract_manifest_profile_config_loads_layout_when_path_present(self, mock_read):
        """Test _extract_manifest_profile_config loads layout when path present."""
        from phone.cli.main import _extract_manifest_profile_config

        mock_read.return_value = {"dock": [], "pages": {}}
        manifest = make_mock_manifest(layout_export_path="export.yaml")

        plan, layout, profile = _extract_manifest_profile_config(manifest)

        self.assertIsNotNone(layout)
        self.assertEqual(layout, {"dock": [], "pages": {}})
        mock_read.assert_called_once()


class TestInlineCommands(unittest.TestCase):
    """Test inline commands that use helper functions."""

    @patch("phone.cli.main.load_layout")
    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main.write_yaml")
    @patch("phone.cli.main.auto_folderize")
    @patch("phone.cli.main.distribute_folders_across_pages")
    def test_auto_folders_reads_plan_and_writes_output(self, mock_dist, mock_auto, mock_write, mock_read, mock_load):
        """Test cmd_auto_folders reads plan, auto-folderizes, and writes output."""
        from phone.cli.main import cmd_auto_folders
        from phone.layout import NormalizedLayout

        mock_load.return_value = NormalizedLayout(dock=[], pages=[])
        mock_read.return_value = make_mock_plan()
        mock_auto.return_value = {"Work": ["app1"], "Utils": ["app2"]}
        mock_dist.return_value = {2: ["Work", "Utils"]}
        args = make_auto_folders_args(plan="plan.yaml", out="folderized.yaml")

        result = cmd_auto_folders(args)

        self.assertEqual(result, 0)
        mock_write.assert_called_once()

    @patch("phone.cli.main.load_layout")
    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main.auto_folderize")
    @patch("phone.cli.main.distribute_folders_across_pages")
    @patch("phone.cli.main.write_yaml")
    def test_auto_folders_uses_keep_list(self, mock_write, mock_dist, mock_auto, mock_read, mock_load):
        """Test cmd_auto_folders passes parsed keep list to auto_folderize."""
        from phone.cli.main import cmd_auto_folders
        from phone.layout import NormalizedLayout

        mock_load.return_value = NormalizedLayout(dock=[], pages=[])
        mock_read.return_value = make_mock_plan()
        mock_auto.return_value = {}
        mock_dist.return_value = {}
        args = make_auto_folders_args(keep="com.app1,com.app2")

        cmd_auto_folders(args)

        # Check that auto_folderize was called with parsed keep list
        call_kwargs = mock_auto.call_args[1]
        self.assertEqual(call_kwargs["keep"], ["com.app1", "com.app2"])

    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main._build_manifest_dict")
    @patch("phone.cli.main.write_yaml")
    def test_manifest_create_delegates_to_helper(self, mock_write, mock_build, mock_read):
        """Test cmd_manifest_create uses _build_manifest_dict helper."""
        from phone.cli.main import cmd_manifest_create

        plan = make_mock_plan()
        manifest = make_mock_manifest(plan=plan)
        mock_read.return_value = plan
        mock_build.return_value = manifest
        args = make_manifest_create_args(from_plan="plan.yaml", out="manifest.yaml")

        result = cmd_manifest_create(args)

        self.assertEqual(result, 0)
        mock_read.assert_called_once()
        mock_build.assert_called_once_with(plan, args)
        mock_write.assert_called_once_with(manifest, Path("manifest.yaml"))

    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main._extract_manifest_profile_config")
    @patch("phone.cli.main.build_mobileconfig")
    def test_manifest_build_delegates_to_helper(self, mock_build, mock_extract, mock_read):
        """Test cmd_manifest_build uses _extract_manifest_profile_config helper."""
        from phone.cli.main import cmd_manifest_build

        manifest = make_mock_manifest()
        mock_read.return_value = manifest
        mock_extract.return_value = (make_mock_plan(), None, manifest["profile"])
        mock_build.return_value = {"test": "profile"}
        args = make_manifest_build_args(manifest="manifest.yaml", out="profile.mobileconfig")

        with patch("plistlib.dump"), patch("phone.cli.main.Path"):
            result = cmd_manifest_build(args)

        self.assertEqual(result, 0)
        mock_extract.assert_called_once_with(manifest)

    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main._extract_manifest_profile_config")
    def test_manifest_build_handles_invalid_manifest(self, mock_extract, mock_read):
        """Test cmd_manifest_build handles ValueError from helper."""
        from phone.cli.main import cmd_manifest_build

        mock_read.return_value = {}
        mock_extract.side_effect = ValueError("manifest missing 'plan' section")
        args = make_manifest_build_args(manifest="bad.yaml")

        result = cmd_manifest_build(args)

        self.assertEqual(result, 2)  # Error code

    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main.build_mobileconfig")
    @patch("phone.cli.main._build_all_apps_folder_config")
    @patch("phone.cli.main._write_mobileconfig")
    def test_profile_build_uses_all_apps_folder_helper(self, mock_write, mock_folder, mock_build, mock_read):
        """Test cmd_profile_build uses _build_all_apps_folder_config helper."""
        from phone.cli.main import cmd_profile_build

        mock_read.return_value = make_mock_plan()
        mock_folder.return_value = {"name": "All Apps", "page": 5}
        mock_build.return_value = {"test": "profile"}
        args = make_profile_build_args(plan="plan.yaml", all_apps_folder_name="All Apps")

        result = cmd_profile_build(args)

        self.assertEqual(result, 0)
        mock_folder.assert_called_once()
        mock_write.assert_called_once()


class TestAutoFoldersCommand(unittest.TestCase):
    """Test auto_folders command end-to-end."""

    @patch("phone.cli.main.load_layout")
    @patch("phone.cli.main.Path")
    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main.write_yaml")
    @patch("phone.cli.main.auto_folderize")
    @patch("phone.cli.main.distribute_folders_across_pages")
    def test_auto_folders_preserves_page1_when_start_page_is_2(
        self, mock_distribute, mock_auto, mock_write, mock_read, mock_path, mock_load
    ):
        """Test auto_folders preserves page 1 when start_page=2."""
        from phone.cli.main import cmd_auto_folders
        from phone.layout import NormalizedLayout

        # Mock Path to make plan_path.exists() return True
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        mock_load.return_value = NormalizedLayout(dock=[], pages=[])
        plan = make_mock_plan(pages={1: ["kept"], 3: ["cleared"]})
        mock_read.return_value = plan
        mock_auto.return_value = {"Work": ["app1"]}
        mock_distribute.return_value = {2: ["Work"]}
        args = make_auto_folders_args(plan="plan.yaml")
        args.place_folders_from_page = 2
        args.folders_per_page = 12

        cmd_auto_folders(args)

        # Check that written plan has page 1 preserved
        written_plan = mock_write.call_args[0][0]
        self.assertIn(1, written_plan["pages"])

    @patch("phone.cli.main.load_layout")
    @patch("phone.cli.main.Path")
    @patch("phone.cli.main.read_yaml")
    @patch("phone.cli.main.write_yaml")
    @patch("phone.cli.main.auto_folderize")
    @patch("phone.cli.main.distribute_folders_across_pages")
    def test_auto_folders_with_layout_loads_export(self, mock_dist, mock_auto, mock_write, mock_read, mock_path, mock_load):
        """Test auto_folders loads layout when provided."""
        from phone.cli.main import cmd_auto_folders
        from phone.layout import NormalizedLayout

        # Mock Path.exists() to return False so plan doesn't load
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        mock_load.return_value = NormalizedLayout(dock=[], pages=[])
        mock_auto.return_value = {}
        mock_dist.return_value = {}
        args = make_auto_folders_args(layout="export.yaml")

        cmd_auto_folders(args)

        # load_layout should have been called
        mock_load.assert_called_once()

    @patch("phone.cli.main.load_layout")
    def test_auto_folders_handles_layout_load_error(self, mock_load):
        """Test auto_folders handles LayoutLoadError gracefully."""
        from phone.cli.main import cmd_auto_folders
        from phone.helpers import LayoutLoadError

        mock_load.side_effect = LayoutLoadError(code=2, message="No backup found")
        args = make_auto_folders_args(plan="missing.yaml")

        result = cmd_auto_folders(args)

        self.assertEqual(result, 2)  # Should return the error code
