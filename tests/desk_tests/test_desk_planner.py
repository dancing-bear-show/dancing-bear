"""Tests for desk/planner.py - file organization planning."""

import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fixtures import TempDirMixin, write_yaml

from desk.planner import (
    MatchCriteria,
    _build_operation,
    _file_matches_criteria,
    _parse_rule,
    _scan_directory,
    plan_from_config,
)


class TestMatchCriteria(unittest.TestCase):
    """Tests for MatchCriteria dataclass."""

    def test_match_criteria_defaults(self):
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=None)
        self.assertEqual(criteria.extensions, [])
        self.assertIsNone(criteria.size_threshold)
        self.assertIsNone(criteria.age_threshold)

    def test_match_criteria_with_values(self):
        criteria = MatchCriteria(
            extensions=[".txt", ".log"],
            size_threshold=1024,
            age_threshold=86400,
        )
        self.assertEqual(criteria.extensions, [".txt", ".log"])
        self.assertEqual(criteria.size_threshold, 1024)
        self.assertEqual(criteria.age_threshold, 86400)


class TestFileMatchesCriteria(TempDirMixin, unittest.TestCase):
    """Tests for _file_matches_criteria function."""

    def _create_file(self, name: str, size: int = 100, age_days: float = 0) -> os.stat_result:
        """Create a file and return its stat result."""
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        if age_days > 0:
            mtime = time.time() - (age_days * 86400)
            os.utime(path, (mtime, mtime))
        return os.stat(path)

    def test_no_criteria_matches_all(self):
        stat = self._create_file("test.txt")
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=None)
        self.assertTrue(_file_matches_criteria("test.txt", stat, criteria))

    def test_extension_match(self):
        stat = self._create_file("test.txt")
        criteria = MatchCriteria(extensions=[".txt"], size_threshold=None, age_threshold=None)
        self.assertTrue(_file_matches_criteria("test.txt", stat, criteria))

    def test_extension_no_match(self):
        stat = self._create_file("test.txt")
        criteria = MatchCriteria(extensions=[".log"], size_threshold=None, age_threshold=None)
        self.assertFalse(_file_matches_criteria("test.txt", stat, criteria))

    def test_extension_case_insensitive(self):
        stat = self._create_file("test.TXT")
        criteria = MatchCriteria(extensions=[".txt"], size_threshold=None, age_threshold=None)
        self.assertTrue(_file_matches_criteria("test.TXT", stat, criteria))

    def test_multiple_extensions(self):
        stat = self._create_file("test.log")
        criteria = MatchCriteria(extensions=[".txt", ".log"], size_threshold=None, age_threshold=None)
        self.assertTrue(_file_matches_criteria("test.log", stat, criteria))

    def test_size_threshold_passes(self):
        stat = self._create_file("big.txt", size=1000)
        criteria = MatchCriteria(extensions=[], size_threshold=500, age_threshold=None)
        self.assertTrue(_file_matches_criteria("big.txt", stat, criteria))

    def test_size_threshold_fails(self):
        stat = self._create_file("small.txt", size=100)
        criteria = MatchCriteria(extensions=[], size_threshold=500, age_threshold=None)
        self.assertFalse(_file_matches_criteria("small.txt", stat, criteria))

    def test_age_threshold_passes(self):
        stat = self._create_file("old.txt", age_days=10)
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=86400)  # 1 day
        self.assertTrue(_file_matches_criteria("old.txt", stat, criteria))

    def test_age_threshold_fails(self):
        stat = self._create_file("new.txt", age_days=0)
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=86400)  # 1 day
        self.assertFalse(_file_matches_criteria("new.txt", stat, criteria))

    def test_combined_criteria_all_pass(self):
        stat = self._create_file("test.log", size=1000, age_days=10)
        criteria = MatchCriteria(
            extensions=[".log"],
            size_threshold=500,
            age_threshold=86400,
        )
        self.assertTrue(_file_matches_criteria("test.log", stat, criteria))

    def test_combined_criteria_one_fails(self):
        stat = self._create_file("test.log", size=100, age_days=10)  # size too small
        criteria = MatchCriteria(
            extensions=[".log"],
            size_threshold=500,
            age_threshold=86400,
        )
        self.assertFalse(_file_matches_criteria("test.log", stat, criteria))


class TestBuildOperation(unittest.TestCase):
    """Tests for _build_operation function."""

    def test_move_action(self):
        op = _build_operation("/src/file.txt", "file.txt", {"move_to": "/dest"}, "rule1")
        self.assertEqual(op["action"], "move")
        self.assertEqual(op["src"], "/src/file.txt")
        self.assertEqual(op["dest"], "/dest/file.txt")
        self.assertEqual(op["rule"], "rule1")

    def test_trash_action(self):
        op = _build_operation("/src/file.txt", "file.txt", {"trash": True}, "rule2")
        self.assertEqual(op["action"], "trash")
        self.assertEqual(op["src"], "/src/file.txt")
        self.assertEqual(op["rule"], "rule2")
        self.assertNotIn("dest", op)

    def test_no_action(self):
        op = _build_operation("/src/file.txt", "file.txt", {}, "rule3")
        self.assertIsNone(op)

    def test_move_takes_precedence_over_trash(self):
        op = _build_operation("/src/file.txt", "file.txt", {"move_to": "/dest", "trash": True}, "rule4")
        self.assertEqual(op["action"], "move")

    def test_move_to_expands_user(self):
        with patch("os.path.expanduser", return_value="/home/user/dest"):
            op = _build_operation("/src/file.txt", "file.txt", {"move_to": "~/dest"}, "rule5")
            self.assertEqual(op["dest"], "/home/user/dest/file.txt")


class TestParseRule(unittest.TestCase):
    """Tests for _parse_rule function."""

    def test_empty_rule(self):
        criteria, action, paths, rule_name = _parse_rule({})
        self.assertEqual(criteria.extensions, [])
        self.assertIsNone(criteria.size_threshold)
        self.assertIsNone(criteria.age_threshold)
        self.assertEqual(action, {})
        self.assertEqual(rule_name, "")

    def test_full_rule(self):
        rule = {
            "name": "cleanup",
            "match": {
                "paths": ["/tmp"],
                "extensions": [".TMP", ".log"],
                "size_gte": "1MB",
                "older_than": "7d",
            },
            "action": {"move_to": "/archive"},
        }
        criteria, action, paths, rule_name = _parse_rule(rule)

        self.assertEqual(criteria.extensions, [".tmp", ".log"])  # lowercased
        self.assertEqual(criteria.size_threshold, 1024 * 1024)
        self.assertEqual(criteria.age_threshold, 7 * 86400)
        self.assertEqual(action, {"move_to": "/archive"})
        self.assertEqual(rule_name, "cleanup")

    def test_extensions_lowercased(self):
        rule = {"match": {"extensions": [".TXT", ".LOG", ".Csv"]}}
        criteria, _, _, _ = _parse_rule(rule)
        self.assertEqual(criteria.extensions, [".txt", ".log", ".csv"])


class TestScanDirectory(TempDirMixin, unittest.TestCase):
    """Tests for _scan_directory function."""

    def test_empty_directory(self):
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=None)
        ops = _scan_directory(self.tmpdir, criteria, {"trash": True}, "test")
        self.assertEqual(ops, [])

    def test_nonexistent_directory(self):
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=None)
        ops = _scan_directory("/nonexistent/path", criteria, {"trash": True}, "test")
        self.assertEqual(ops, [])

    def test_finds_matching_files(self):
        # Create test files
        Path(self.tmpdir, "file1.txt").write_text("content")
        Path(self.tmpdir, "file2.txt").write_text("content")
        Path(self.tmpdir, "file3.log").write_text("content")

        criteria = MatchCriteria(extensions=[".txt"], size_threshold=None, age_threshold=None)
        ops = _scan_directory(self.tmpdir, criteria, {"trash": True}, "cleanup")

        self.assertEqual(len(ops), 2)
        srcs = [op["src"] for op in ops]
        self.assertIn(os.path.join(self.tmpdir, "file1.txt"), srcs)
        self.assertIn(os.path.join(self.tmpdir, "file2.txt"), srcs)

    def test_recursive_scan(self):
        # Create nested structure
        subdir = os.path.join(self.tmpdir, "sub")
        os.makedirs(subdir)
        Path(self.tmpdir, "root.txt").write_text("content")
        Path(subdir, "nested.txt").write_text("content")

        criteria = MatchCriteria(extensions=[".txt"], size_threshold=None, age_threshold=None)
        ops = _scan_directory(self.tmpdir, criteria, {"trash": True}, "test")

        self.assertEqual(len(ops), 2)

    def test_no_action_produces_no_ops(self):
        Path(self.tmpdir, "file.txt").write_text("content")
        criteria = MatchCriteria(extensions=[], size_threshold=None, age_threshold=None)
        ops = _scan_directory(self.tmpdir, criteria, {}, "test")
        self.assertEqual(ops, [])


class TestPlanFromConfig(TempDirMixin, unittest.TestCase):
    """Tests for plan_from_config function."""

    def test_missing_config_raises(self):
        with self.assertRaises(FileNotFoundError):
            plan_from_config("/nonexistent/config.yaml")

    def test_empty_config(self):
        config_path = write_yaml({}, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(result["version"], 1)
        self.assertEqual(result["operations"], [])
        self.assertIn("generated_from", result)

    def test_config_with_version(self):
        config_path = write_yaml({"version": 2}, self.tmpdir)
        result = plan_from_config(config_path)
        self.assertEqual(result["version"], 2)

    def test_simple_rule(self):
        # Create target directory and files
        target_dir = os.path.join(self.tmpdir, "target")
        os.makedirs(target_dir)
        Path(target_dir, "file.txt").write_text("content")

        config = {
            "version": 1,
            "rules": [
                {
                    "name": "cleanup",
                    "match": {"paths": [target_dir], "extensions": [".txt"]},
                    "action": {"trash": True},
                }
            ],
        }
        config_path = write_yaml(config, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(len(result["operations"]), 1)
        self.assertEqual(result["operations"][0]["action"], "trash")
        self.assertEqual(result["operations"][0]["rule"], "cleanup")

    def test_move_action(self):
        target_dir = os.path.join(self.tmpdir, "source")
        archive_dir = os.path.join(self.tmpdir, "archive")
        os.makedirs(target_dir)
        Path(target_dir, "data.log").write_text("log content")

        config = {
            "rules": [
                {
                    "match": {"paths": [target_dir], "extensions": [".log"]},
                    "action": {"move_to": archive_dir},
                }
            ],
        }
        config_path = write_yaml(config, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(len(result["operations"]), 1)
        op = result["operations"][0]
        self.assertEqual(op["action"], "move")
        self.assertEqual(op["dest"], os.path.join(archive_dir, "data.log"))

    def test_multiple_rules(self):
        dir1 = os.path.join(self.tmpdir, "dir1")
        dir2 = os.path.join(self.tmpdir, "dir2")
        os.makedirs(dir1)
        os.makedirs(dir2)
        Path(dir1, "file.txt").write_text("content")
        Path(dir2, "file.log").write_text("content")

        config = {
            "rules": [
                {
                    "name": "rule1",
                    "match": {"paths": [dir1]},
                    "action": {"trash": True},
                },
                {
                    "name": "rule2",
                    "match": {"paths": [dir2]},
                    "action": {"trash": True},
                },
            ],
        }
        config_path = write_yaml(config, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(len(result["operations"]), 2)
        rules = {op["rule"] for op in result["operations"]}
        self.assertEqual(rules, {"rule1", "rule2"})

    def test_size_filter(self):
        target_dir = os.path.join(self.tmpdir, "target")
        os.makedirs(target_dir)

        # Create small and large files
        Path(target_dir, "small.txt").write_text("x")
        Path(target_dir, "large.txt").write_text("x" * 1000)

        config = {
            "rules": [
                {
                    "match": {"paths": [target_dir], "size_gte": "500"},
                    "action": {"trash": True},
                }
            ],
        }
        config_path = write_yaml(config, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(len(result["operations"]), 1)
        self.assertIn("large.txt", result["operations"][0]["src"])

    def test_age_filter(self):
        target_dir = os.path.join(self.tmpdir, "target")
        os.makedirs(target_dir)

        # Create new file
        new_file = Path(target_dir, "new.txt")
        new_file.write_text("content")

        # Create old file (10 days ago)
        old_file = Path(target_dir, "old.txt")
        old_file.write_text("content")
        old_mtime = time.time() - (10 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))

        config = {
            "rules": [
                {
                    "match": {"paths": [target_dir], "older_than": "7d"},
                    "action": {"trash": True},
                }
            ],
        }
        config_path = write_yaml(config, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(len(result["operations"]), 1)
        self.assertIn("old.txt", result["operations"][0]["src"])

    def test_nonexistent_target_path_skipped(self):
        config = {
            "rules": [
                {
                    "match": {"paths": ["/nonexistent/path"]},
                    "action": {"trash": True},
                }
            ],
        }
        config_path = write_yaml(config, self.tmpdir)
        result = plan_from_config(config_path)

        self.assertEqual(result["operations"], [])


if __name__ == "__main__":
    unittest.main()
