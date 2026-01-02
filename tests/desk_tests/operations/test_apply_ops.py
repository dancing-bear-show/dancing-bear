"""Tests for desk/apply_ops.py file operation application."""

import json
import os
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

from desk.apply_ops import apply_plan_file, _load_data, _do_move, _do_trash


class LoadDataTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_json(self):
        path = os.path.join(self.tmpdir, "plan.json")
        data = {"operations": [{"action": "move"}]}
        with open(path, "w") as f:
            json.dump(data, f)

        result = _load_data(path)
        self.assertEqual(result, data)

    def test_load_yaml(self):
        path = os.path.join(self.tmpdir, "plan.yaml")
        with open(path, "w") as f:
            f.write("operations:\n  - action: move\n")

        result = _load_data(path)
        self.assertEqual(result["operations"][0]["action"], "move")

    def test_load_yml(self):
        path = os.path.join(self.tmpdir, "plan.yml")
        with open(path, "w") as f:
            f.write("operations:\n  - action: trash\n")

        result = _load_data(path)
        self.assertEqual(result["operations"][0]["action"], "trash")


class DoMoveTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_move_file(self):
        src = os.path.join(self.tmpdir, "source.txt")
        dest_dir = os.path.join(self.tmpdir, "dest")
        dest = os.path.join(dest_dir, "source.txt")

        with open(src, "w") as f:
            f.write("content")

        _do_move(src, dest, dry_run=False)

        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.exists(dest))

    def test_move_creates_dest_dir(self):
        src = os.path.join(self.tmpdir, "source.txt")
        dest_dir = os.path.join(self.tmpdir, "nested", "dest")
        dest = os.path.join(dest_dir, "source.txt")

        with open(src, "w") as f:
            f.write("content")

        _do_move(src, dest, dry_run=False)

        self.assertTrue(os.path.isdir(dest_dir))
        self.assertTrue(os.path.exists(dest))

    def test_move_dry_run(self):
        src = os.path.join(self.tmpdir, "source.txt")
        dest = os.path.join(self.tmpdir, "dest", "source.txt")

        with open(src, "w") as f:
            f.write("content")

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            _do_move(src, dest, dry_run=True)
            output = mock_out.getvalue()

        self.assertTrue(os.path.exists(src))  # Still exists
        self.assertFalse(os.path.exists(dest))  # Not moved
        self.assertIn("DRY-RUN", output)


class DoTrashTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_trash_dry_run(self):
        src = os.path.join(self.tmpdir, "to_delete.txt")
        with open(src, "w") as f:
            f.write("content")

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            _do_trash(src, dry_run=True)
            output = mock_out.getvalue()

        self.assertTrue(os.path.exists(src))  # Still exists
        self.assertIn("DRY-RUN", output)
        self.assertIn("trash", output.lower())


class ApplyPlanFileTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_apply_move_operation(self):
        src = os.path.join(self.tmpdir, "source.txt")
        dest_dir = os.path.join(self.tmpdir, "dest")
        dest = os.path.join(dest_dir, "source.txt")

        with open(src, "w") as f:
            f.write("content")

        plan_path = os.path.join(self.tmpdir, "plan.json")
        plan = {
            "operations": [
                {"action": "move", "src": src, "dest": dest}
            ]
        }
        with open(plan_path, "w") as f:
            json.dump(plan, f)

        apply_plan_file(plan_path, dry_run=False)

        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.exists(dest))

    def test_apply_dry_run(self):
        src = os.path.join(self.tmpdir, "source.txt")
        dest = os.path.join(self.tmpdir, "dest", "source.txt")

        with open(src, "w") as f:
            f.write("content")

        plan_path = os.path.join(self.tmpdir, "plan.json")
        plan = {
            "operations": [
                {"action": "move", "src": src, "dest": dest}
            ]
        }
        with open(plan_path, "w") as f:
            json.dump(plan, f)

        apply_plan_file(plan_path, dry_run=True)

        self.assertTrue(os.path.exists(src))  # Still exists
        self.assertFalse(os.path.exists(dest))  # Not moved

    def test_apply_multiple_operations(self):
        src1 = os.path.join(self.tmpdir, "file1.txt")
        src2 = os.path.join(self.tmpdir, "file2.txt")
        dest_dir = os.path.join(self.tmpdir, "dest")
        dest1 = os.path.join(dest_dir, "file1.txt")
        dest2 = os.path.join(dest_dir, "file2.txt")

        with open(src1, "w") as f:
            f.write("content1")
        with open(src2, "w") as f:
            f.write("content2")

        plan_path = os.path.join(self.tmpdir, "plan.json")
        plan = {
            "operations": [
                {"action": "move", "src": src1, "dest": dest1},
                {"action": "move", "src": src2, "dest": dest2},
            ]
        }
        with open(plan_path, "w") as f:
            json.dump(plan, f)

        apply_plan_file(plan_path, dry_run=False)

        self.assertTrue(os.path.exists(dest1))
        self.assertTrue(os.path.exists(dest2))

    def test_apply_empty_plan(self):
        plan_path = os.path.join(self.tmpdir, "plan.json")
        with open(plan_path, "w") as f:
            json.dump({"operations": []}, f)

        # Should not raise
        apply_plan_file(plan_path, dry_run=False)

    def test_unknown_action_prints_message(self):
        plan_path = os.path.join(self.tmpdir, "plan.json")
        plan = {
            "operations": [
                {"action": "unknown_action", "src": "/some/path"}
            ]
        }
        with open(plan_path, "w") as f:
            json.dump(plan, f)

        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            apply_plan_file(plan_path, dry_run=False)
            output = mock_out.getvalue()

        self.assertIn("unknown", output.lower())


if __name__ == "__main__":
    unittest.main()
