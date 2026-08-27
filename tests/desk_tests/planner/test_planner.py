"""Tests for desk/planner.py plan generation from config."""

import os
import time
import unittest

from tests.fixtures import TempDirMixin
from core.cli_errors import NotFoundError
from desk.planner import plan_from_config


class PlanFromConfigTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.test_files_dir = os.path.join(self.tmpdir, "files")
        os.makedirs(self.test_files_dir)

    def tearDown(self):
        super().tearDown()

    def _write_config(self, content: str) -> str:
        config_path = os.path.join(self.tmpdir, "config.yaml")
        with open(config_path, "w") as f:
            f.write(content)
        return config_path

    def _create_test_file(self, name: str, size: int = 100, age_days: int = 0, base_dir: str | None = None) -> str:
        path = os.path.join(base_dir or self.test_files_dir, name)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        if age_days > 0:
            old_time = time.time() - (age_days * 86400)
            os.utime(path, (old_time, old_time))
        return path

    def test_nonexistent_config_raises(self):
        with self.assertRaises(NotFoundError):
            plan_from_config("/nonexistent/config.yaml")

    def test_empty_config(self):
        config = self._write_config("version: 1\nrules: []")
        result = plan_from_config(config)

        self.assertEqual(result["version"], 1)
        self.assertEqual(result["operations"], [])

    def test_returns_generated_from(self):
        config = self._write_config("version: 1\nrules: []")
        result = plan_from_config(config)

        self.assertIn("generated_from", result)
        self.assertTrue(os.path.isabs(result["generated_from"]))

    def test_move_action(self):
        self._create_test_file("test.txt")
        dest_dir = os.path.join(self.tmpdir, "dest")

        config = self._write_config(f"""
version: 1
rules:
  - name: move-txt
    match:
      paths:
        - {self.test_files_dir}
      extensions:
        - .txt
    action:
      move_to: {dest_dir}
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 1)
        op = result["operations"][0]
        self.assertEqual(op["action"], "move")
        self.assertIn("test.txt", op["src"])
        self.assertIn(dest_dir, op["dest"])

    def test_trash_action(self):
        self._create_test_file("delete_me.log")

        config = self._write_config(f"""
version: 1
rules:
  - name: trash-logs
    match:
      paths:
        - {self.test_files_dir}
      extensions:
        - .log
    action:
      trash: true
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 1)
        self.assertEqual(result["operations"][0]["action"], "trash")

    def test_extension_filter(self):
        self._create_test_file("file.txt")
        self._create_test_file("file.log")

        config = self._write_config(f"""
version: 1
rules:
  - name: txt-only
    match:
      paths:
        - {self.test_files_dir}
      extensions:
        - .txt
    action:
      trash: true
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 1)
        self.assertIn("file.txt", result["operations"][0]["src"])

    def test_size_and_age_filters(self):
        cases = [
            (
                "size_gte",
                dict(name="small.txt", size=100),
                dict(name="large.txt", size=2000),
                "large-files",
                "size_gte: 1KB",
                "large.txt",
            ),
            (
                "older_than",
                dict(name="new.txt", age_days=0),
                dict(name="old.txt", age_days=40),
                "old-files",
                "older_than: 30d",
                "old.txt",
            ),
        ]
        for match_key, excluded, included, rule_name, match_line, expected_src in cases:
            with self.subTest(match_key):
                case_dir = os.path.join(self.test_files_dir, match_key)
                os.makedirs(case_dir)

                self._create_test_file(base_dir=case_dir, **excluded)
                self._create_test_file(base_dir=case_dir, **included)

                config = self._write_config(f"""
version: 1
rules:
  - name: {rule_name}
    match:
      paths:
        - {case_dir}
      {match_line}
    action:
      trash: true
""")
                result = plan_from_config(config)

                self.assertEqual(len(result["operations"]), 1)
                self.assertIn(expected_src, result["operations"][0]["src"])

    def test_rule_name_in_operation(self):
        self._create_test_file("test.txt")

        config = self._write_config(f"""
version: 1
rules:
  - name: my-rule-name
    match:
      paths:
        - {self.test_files_dir}
    action:
      trash: true
""")
        result = plan_from_config(config)

        self.assertEqual(result["operations"][0]["rule"], "my-rule-name")

    def test_multiple_rules(self):
        self._create_test_file("file.txt")
        self._create_test_file("file.log")
        dest1 = os.path.join(self.tmpdir, "dest1")
        dest2 = os.path.join(self.tmpdir, "dest2")

        config = self._write_config(f"""
version: 1
rules:
  - name: move-txt
    match:
      paths:
        - {self.test_files_dir}
      extensions:
        - .txt
    action:
      move_to: {dest1}
  - name: move-log
    match:
      paths:
        - {self.test_files_dir}
      extensions:
        - .log
    action:
      move_to: {dest2}
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 2)

    def test_nonexistent_match_path(self):
        config = self._write_config("""
version: 1
rules:
  - name: missing-path
    match:
      paths:
        - /nonexistent/path/here
    action:
      trash: true
""")
        result = plan_from_config(config)
        self.assertEqual(result["operations"], [])

    def test_extension_case_insensitive(self):
        self._create_test_file("FILE.TXT")

        config = self._write_config(f"""
version: 1
rules:
  - name: txt-files
    match:
      paths:
        - {self.test_files_dir}
      extensions:
        - .txt
    action:
      trash: true
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 1)


if __name__ == "__main__":
    unittest.main()
