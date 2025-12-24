import os
import tempfile
import time
import unittest
from pathlib import Path

try:
    from resume.resume import cleanup
except ModuleNotFoundError:
    from resume import cleanup


class TestCleanup(unittest.TestCase):
    def test_build_tidy_plan_filters_and_orders(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f_old = base / "sample_old.json"
            f_new = base / "sample_new.json"
            f_other = base / "other.json"
            f_old.write_text("old", encoding="utf-8")
            f_new.write_text("new", encoding="utf-8")
            f_other.write_text("other", encoding="utf-8")
            now = time.time()
            os.utime(f_old, (now - 10, now - 10))
            os.utime(f_new, (now, now))

            plan = cleanup.build_tidy_plan(
                base,
                prefix="sample",
                suffixes=[".json"],
                keep=1,
            )

            self.assertEqual([p.name for p in plan.keep], ["sample_new.json"])
            self.assertEqual([p.name for p in plan.move], ["sample_old.json"])
            self.assertEqual(plan.archive_dir, base / "archive")

    def test_execute_archive_moves_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f1 = base / "sample_a.json"
            f2 = base / "sample_b.json"
            f1.write_text("a", encoding="utf-8")
            f2.write_text("b", encoding="utf-8")

            plan = cleanup.build_tidy_plan(base, prefix="sample", suffixes=[".json"], keep=0)
            moved = cleanup.execute_archive(plan, subfolder="test")

            self.assertEqual({p.name for p in moved}, {"sample_a.json", "sample_b.json"})
            for p in moved:
                self.assertTrue(p.exists())
                self.assertEqual(p.parent, base / "archive" / "test")
            self.assertFalse(f1.exists())
            self.assertFalse(f2.exists())

    def test_execute_delete_removes_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            f1 = base / "delete_me.json"
            f1.write_text("delete", encoding="utf-8")

            plan = cleanup.build_tidy_plan(base, prefix="delete", suffixes=[".json"], keep=0)
            deleted = cleanup.execute_delete(plan)

            self.assertEqual([p.name for p in deleted], ["delete_me.json"])
            self.assertFalse(f1.exists())

    def test_purge_temp_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            nested = base / "nested"
            nested.mkdir()
            temp_docx = nested / "~$temp.docx"
            ds_store = base / ".DS_Store"
            keep = base / "keep.txt"
            temp_docx.write_text("tmp", encoding="utf-8")
            ds_store.write_text("tmp", encoding="utf-8")
            keep.write_text("keep", encoding="utf-8")

            removed = cleanup.purge_temp_files(base)
            removed_names = {p.name for p in removed}

            self.assertIn("~$temp.docx", removed_names)
            self.assertIn(".DS_Store", removed_names)
            self.assertTrue(keep.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
