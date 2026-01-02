"""Tests for desk/planner.py plan generation from config."""

import os
import tempfile
import time
import unittest

from desk.planner import plan_from_config


class PlanFromConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_files_dir = os.path.join(self.tmpdir, "files")
        os.makedirs(self.test_files_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_config(self, content: str) -> str:
        config_path = os.path.join(self.tmpdir, "config.yaml")
        with open(config_path, "w") as f:
            f.write(content)
        return config_path

    def _create_test_file(self, name: str, size: int = 100, age_days: int = 0) -> str:
        path = os.path.join(self.test_files_dir, name)
        with open(path, "wb") as f:
            f.write(b"x" * size)
        if age_days > 0:
            old_time = time.time() - (age_days * 86400)
            os.utime(path, (old_time, old_time))
        return path

    def test_nonexistent_config_raises(self):
        with self.assertRaises(FileNotFoundError):
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

    def test_size_filter(self):
        self._create_test_file("small.txt", size=100)
        self._create_test_file("large.txt", size=2000)

        config = self._write_config(f"""
version: 1
rules:
  - name: large-files
    match:
      paths:
        - {self.test_files_dir}
      size_gte: 1KB
    action:
      trash: true
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 1)
        self.assertIn("large.txt", result["operations"][0]["src"])

    def test_age_filter(self):
        self._create_test_file("new.txt", age_days=0)
        self._create_test_file("old.txt", age_days=40)

        config = self._write_config(f"""
version: 1
rules:
  - name: old-files
    match:
      paths:
        - {self.test_files_dir}
      older_than: 30d
    action:
      trash: true
""")
        result = plan_from_config(config)

        self.assertEqual(len(result["operations"]), 1)
        self.assertIn("old.txt", result["operations"][0]["src"])

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
