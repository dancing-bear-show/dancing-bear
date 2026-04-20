"""Tests for phone/helpers.py — layout load helpers."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestWriteYaml(unittest.TestCase):
    def test_write_yaml_calls_dump(self):
        from phone.helpers import write_yaml

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "test.yaml"
            with patch("phone.helpers._dump_yaml") as mock_dump:
                write_yaml({"key": "val"}, out)
                mock_dump.assert_called_once_with(str(out), {"key": "val"})


class TestReadYaml(unittest.TestCase):
    def test_read_yaml_returns_data(self):
        from phone.helpers import read_yaml

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "data.yaml"
            f.write_text("key: value\n")
            with patch("phone.helpers._load_yaml", return_value={"key": "value"}) as mock_load:
                result = read_yaml(f)
                mock_load.assert_called_once_with(str(f))
                self.assertEqual(result, {"key": "value"})

    def test_read_yaml_missing_file_raises(self):
        from phone.helpers import read_yaml

        with self.assertRaises(FileNotFoundError):
            read_yaml(Path("/nonexistent/path.yaml"))

    def test_read_yaml_returns_empty_dict_for_none_load(self):
        from phone.helpers import read_yaml

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "empty.yaml"
            f.write_text("")
            with patch("phone.helpers._load_yaml", return_value=None):
                result = read_yaml(f)
                self.assertEqual(result, {})


class TestLayoutFromExport(unittest.TestCase):
    def test_layout_from_export_basic(self):
        from phone.helpers import _layout_from_export

        export = {
            "dock": ["com.apple.safari", "com.apple.maps"],
            "pages": [
                {"apps": ["com.app1", "com.app2"], "folders": []},
            ],
        }
        layout = _layout_from_export(export)
        self.assertEqual(layout.dock, ["com.apple.safari", "com.apple.maps"])
        self.assertEqual(len(layout.pages), 1)
        self.assertEqual(layout.pages[0][0], {"kind": "app", "id": "com.app1"})

    def test_layout_from_export_with_folders(self):
        from phone.helpers import _layout_from_export

        export = {
            "dock": [],
            "pages": [
                {
                    "apps": [],
                    "folders": [
                        {"name": "Work", "apps": ["com.slack.Slack", "com.outlook"]},
                    ],
                }
            ],
        }
        layout = _layout_from_export(export)
        self.assertEqual(len(layout.pages), 1)
        folder_item = layout.pages[0][0]
        self.assertEqual(folder_item["kind"], "folder")
        self.assertEqual(folder_item["name"], "Work")
        self.assertEqual(folder_item["apps"], ["com.slack.Slack", "com.outlook"])

    def test_layout_from_export_empty(self):
        from phone.helpers import _layout_from_export

        layout = _layout_from_export({})
        self.assertEqual(layout.dock, [])
        self.assertEqual(layout.pages, [])

    def test_layout_from_export_mixed_apps_and_folders(self):
        from phone.helpers import _layout_from_export

        export = {
            "dock": ["com.dock"],
            "pages": [
                {
                    "apps": ["com.app1"],
                    "folders": [{"name": "Tools", "apps": ["com.calc"]}],
                }
            ],
        }
        layout = _layout_from_export(export)
        page = layout.pages[0]
        kinds = [item["kind"] for item in page]
        self.assertIn("app", kinds)
        self.assertIn("folder", kinds)


class TestLoadLayout(unittest.TestCase):
    def test_load_layout_from_yaml_path(self):
        from phone.helpers import load_layout

        export_data = {
            "dock": ["com.apple.safari"],
            "pages": [{"apps": ["com.app1"], "folders": []}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            layout_file = Path(tmp) / "layout.yaml"
            layout_file.write_text("dock:\n  - com.apple.safari\npages:\n  - apps:\n      - com.app1\n    folders: []\n")
            with patch("phone.helpers._load_yaml", return_value=export_data):
                layout = load_layout(str(layout_file), None)
                self.assertEqual(layout.dock, ["com.apple.safari"])

    def test_load_layout_no_backup_raises(self):
        from phone.helpers import load_layout, LayoutLoadError

        with patch("phone.helpers.find_latest_backup_dir", return_value=None):
            with self.assertRaises(LayoutLoadError) as ctx:
                load_layout(None, None)
            self.assertEqual(ctx.exception.code, 2)

    def test_load_layout_backup_not_found_raises(self):
        from phone.helpers import load_layout, LayoutLoadError

        fake_dir = Path("/nonexistent/backup")
        with patch("phone.helpers.find_latest_backup_dir", return_value=fake_dir):
            with self.assertRaises(LayoutLoadError) as ctx:
                load_layout(None, None)
            self.assertEqual(ctx.exception.code, 2)

    def test_load_layout_no_iconstate_file_raises(self):
        from phone.helpers import load_layout, LayoutLoadError

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            with patch("phone.helpers.find_latest_backup_dir", return_value=backup_dir), \
                 patch("phone.helpers.find_iconstate_file", return_value=None):
                with self.assertRaises(LayoutLoadError) as ctx:
                    load_layout(None, None)
                self.assertEqual(ctx.exception.code, 3)

    def test_load_layout_from_iconstate(self):
        from phone.helpers import load_layout

        mock_iconfile = MagicMock()
        mock_iconfile.path = "/fake/iconstate"
        mock_layout = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            backup_dir = Path(tmp)
            with patch("phone.helpers.find_latest_backup_dir", return_value=backup_dir), \
                 patch("phone.helpers.find_iconstate_file", return_value=mock_iconfile), \
                 patch("phone.helpers.load_plist", return_value={}), \
                 patch("phone.helpers.normalize_iconstate", return_value=mock_layout):
                result = load_layout(None, None)
                self.assertIs(result, mock_layout)


class TestReadLinesFile(unittest.TestCase):
    def test_returns_empty_for_none(self):
        from phone.helpers import read_lines_file

        result = read_lines_file(None)
        self.assertEqual(result, [])

    def test_returns_empty_for_missing_file(self):
        from phone.helpers import read_lines_file

        result = read_lines_file("/nonexistent/file.txt")
        self.assertEqual(result, [])

    def test_reads_and_strips_lines(self):
        from phone.helpers import read_lines_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("com.app1\n  com.app2  \n# comment\n\ncom.app3\n")
            fname = f.name

        result = read_lines_file(fname)
        self.assertEqual(result, ["com.app1", "com.app2", "com.app3"])

    def test_ignores_comments(self):
        from phone.helpers import read_lines_file

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# This is a comment\ncom.valid.app\n")
            fname = f.name

        result = read_lines_file(fname)
        self.assertEqual(result, ["com.valid.app"])


if __name__ == "__main__":
    unittest.main()
