"""Tests for desk/scan.py file scanning utilities."""

import os
import tempfile
import unittest

from desk.scan import run_scan, find_duplicates, _sha256_of


class Sha256OfTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_hash_file(self):
        path = os.path.join(self.tmpdir, "test.txt")
        with open(path, "wb") as f:
            f.write(b"hello world")

        result = _sha256_of(path)
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)  # SHA256 hex digest

    def test_same_content_same_hash(self):
        path1 = os.path.join(self.tmpdir, "file1.txt")
        path2 = os.path.join(self.tmpdir, "file2.txt")
        content = b"identical content"

        with open(path1, "wb") as f:
            f.write(content)
        with open(path2, "wb") as f:
            f.write(content)

        self.assertEqual(_sha256_of(path1), _sha256_of(path2))

    def test_different_content_different_hash(self):
        path1 = os.path.join(self.tmpdir, "file1.txt")
        path2 = os.path.join(self.tmpdir, "file2.txt")

        with open(path1, "wb") as f:
            f.write(b"content one")
        with open(path2, "wb") as f:
            f.write(b"content two")

        self.assertNotEqual(_sha256_of(path1), _sha256_of(path2))


class FindDuplicatesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_list(self):
        result = find_duplicates([])
        self.assertEqual(result, [])

    def test_no_duplicates(self):
        path1 = os.path.join(self.tmpdir, "file1.txt")
        path2 = os.path.join(self.tmpdir, "file2.txt")

        with open(path1, "wb") as f:
            f.write(b"content one")
        with open(path2, "wb") as f:
            f.write(b"content two")

        result = find_duplicates([
            (path1, os.path.getsize(path1)),
            (path2, os.path.getsize(path2)),
        ])
        self.assertEqual(result, [])

    def test_finds_duplicates(self):
        path1 = os.path.join(self.tmpdir, "file1.txt")
        path2 = os.path.join(self.tmpdir, "file2.txt")
        content = b"identical content here"

        with open(path1, "wb") as f:
            f.write(content)
        with open(path2, "wb") as f:
            f.write(content)

        size = os.path.getsize(path1)
        result = find_duplicates([(path1, size), (path2, size)])

        self.assertEqual(len(result), 1)
        self.assertIn(path1, result[0])
        self.assertIn(path2, result[0])

    def test_groups_by_size_first(self):
        # Files with different sizes can't be duplicates
        path1 = os.path.join(self.tmpdir, "small.txt")
        path2 = os.path.join(self.tmpdir, "large.txt")

        with open(path1, "wb") as f:
            f.write(b"small")
        with open(path2, "wb") as f:
            f.write(b"much larger content")

        result = find_duplicates([
            (path1, os.path.getsize(path1)),
            (path2, os.path.getsize(path2)),
        ])
        self.assertEqual(result, [])


class RunScanTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scan_empty_dir(self):
        result = run_scan([self.tmpdir], min_size="1MB")

        self.assertIn("paths", result)
        self.assertIn("large_files", result)
        self.assertIn("stale_files", result)
        self.assertIn("top_dirs", result)
        self.assertEqual(result["large_files"], [])

    def test_scan_nonexistent_path(self):
        result = run_scan(["/nonexistent/path"], min_size="1MB")
        self.assertEqual(result["large_files"], [])

    def test_finds_large_files(self):
        # Create a file larger than threshold
        path = os.path.join(self.tmpdir, "large.bin")
        with open(path, "wb") as f:
            f.write(b"x" * 2000)  # 2KB

        result = run_scan([self.tmpdir], min_size="1KB")

        self.assertEqual(len(result["large_files"]), 1)
        self.assertEqual(result["large_files"][0]["path"], path)
        self.assertEqual(result["large_files"][0]["size"], 2000)

    def test_respects_min_size(self):
        path = os.path.join(self.tmpdir, "small.txt")
        with open(path, "wb") as f:
            f.write(b"tiny")

        result = run_scan([self.tmpdir], min_size="1MB")
        self.assertEqual(result["large_files"], [])

    def test_includes_size_human_readable(self):
        path = os.path.join(self.tmpdir, "file.bin")
        with open(path, "wb") as f:
            f.write(b"x" * 2048)  # 2KB

        result = run_scan([self.tmpdir], min_size="1KB")

        self.assertIn("size_h", result["large_files"][0])

    def test_top_dirs_report(self):
        subdir = os.path.join(self.tmpdir, "subdir")
        os.makedirs(subdir)
        path = os.path.join(subdir, "file.bin")
        with open(path, "wb") as f:
            f.write(b"x" * 1000)

        result = run_scan([self.tmpdir], min_size="1", top_dirs=5)

        self.assertIn("top_dirs", result)
        self.assertTrue(len(result["top_dirs"]) > 0)

    def test_sorts_large_files_by_size(self):
        path1 = os.path.join(self.tmpdir, "smaller.bin")
        path2 = os.path.join(self.tmpdir, "larger.bin")

        with open(path1, "wb") as f:
            f.write(b"x" * 1000)
        with open(path2, "wb") as f:
            f.write(b"x" * 2000)

        result = run_scan([self.tmpdir], min_size="500")

        self.assertEqual(result["large_files"][0]["path"], path2)
        self.assertEqual(result["large_files"][1]["path"], path1)

    def test_multiple_paths(self):
        dir1 = os.path.join(self.tmpdir, "dir1")
        dir2 = os.path.join(self.tmpdir, "dir2")
        os.makedirs(dir1)
        os.makedirs(dir2)

        with open(os.path.join(dir1, "file1.bin"), "wb") as f:
            f.write(b"x" * 1000)
        with open(os.path.join(dir2, "file2.bin"), "wb") as f:
            f.write(b"x" * 1000)

        result = run_scan([dir1, dir2], min_size="500")
        self.assertEqual(len(result["large_files"]), 2)

    def test_include_duplicates(self):
        path1 = os.path.join(self.tmpdir, "file1.bin")
        path2 = os.path.join(self.tmpdir, "file2.bin")
        content = b"x" * (1024 * 1024 + 1)  # Just over 1MB

        with open(path1, "wb") as f:
            f.write(content)
        with open(path2, "wb") as f:
            f.write(content)

        result = run_scan([self.tmpdir], min_size="1", include_duplicates=True)

        self.assertIn("duplicates", result)
        self.assertTrue(len(result["duplicates"]) > 0)

    def test_generated_at_timestamp(self):
        result = run_scan([self.tmpdir], min_size="1MB")
        self.assertIn("generated_at", result)
        self.assertIsInstance(result["generated_at"], int)


if __name__ == "__main__":
    unittest.main()
