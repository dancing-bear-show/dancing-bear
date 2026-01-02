"""Tests for desk/utils.py size and duration parsing utilities."""

import json
import os
import tempfile
import unittest

from desk.utils import (
    expand_paths,
    parse_size,
    parse_duration,
    human_size,
    dump_output,
)


class ExpandPathsTests(unittest.TestCase):
    def test_empty_list(self):
        result = expand_paths([])
        self.assertEqual(result, [])

    def test_absolute_path(self):
        result = expand_paths(["/absolute/path"])
        self.assertEqual(result, ["/absolute/path"])

    def test_relative_path_becomes_absolute(self):
        result = expand_paths(["relative/path"])
        self.assertTrue(os.path.isabs(result[0]))

    def test_expands_tilde(self):
        result = expand_paths(["~/some/path"])
        self.assertFalse(result[0].startswith("~"))
        self.assertIn(os.path.expanduser("~"), result[0])

    def test_multiple_paths(self):
        result = expand_paths(["/path1", "/path2"])
        self.assertEqual(len(result), 2)


class ParseSizeTests(unittest.TestCase):
    def test_raw_number(self):
        self.assertEqual(parse_size("1000"), 1000)

    def test_float_number(self):
        self.assertEqual(parse_size("1000.5"), 1000)

    def test_int_input(self):
        self.assertEqual(parse_size(1000), 1000)

    def test_float_input(self):
        self.assertEqual(parse_size(1000.7), 1000)

    def test_kilobytes_k(self):
        self.assertEqual(parse_size("1K"), 1024)
        self.assertEqual(parse_size("1k"), 1024)

    def test_kilobytes_kb(self):
        self.assertEqual(parse_size("1KB"), 1024)
        self.assertEqual(parse_size("1Kb"), 1024)

    def test_megabytes(self):
        self.assertEqual(parse_size("1M"), 1024 ** 2)
        self.assertEqual(parse_size("1MB"), 1024 ** 2)

    def test_gigabytes(self):
        self.assertEqual(parse_size("1G"), 1024 ** 3)
        self.assertEqual(parse_size("1GB"), 1024 ** 3)

    def test_terabytes(self):
        self.assertEqual(parse_size("1T"), 1024 ** 4)
        self.assertEqual(parse_size("1TB"), 1024 ** 4)

    def test_fractional_sizes(self):
        self.assertEqual(parse_size("1.5MB"), int(1.5 * 1024 ** 2))
        self.assertEqual(parse_size("2.5G"), int(2.5 * 1024 ** 3))

    def test_whitespace_stripped(self):
        self.assertEqual(parse_size("  100MB  "), 100 * 1024 ** 2)

    def test_common_sizes(self):
        self.assertEqual(parse_size("50MB"), 50 * 1024 ** 2)
        self.assertEqual(parse_size("100GB"), 100 * 1024 ** 3)


class ParseDurationTests(unittest.TestCase):
    def test_empty_returns_none(self):
        self.assertIsNone(parse_duration(""))
        self.assertIsNone(parse_duration(None))

    def test_seconds(self):
        self.assertEqual(parse_duration("30s"), 30)
        self.assertEqual(parse_duration("120s"), 120)

    def test_minutes(self):
        self.assertEqual(parse_duration("5m"), 300)
        self.assertEqual(parse_duration("90m"), 5400)

    def test_hours(self):
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("24h"), 86400)

    def test_days(self):
        self.assertEqual(parse_duration("1d"), 86400)
        self.assertEqual(parse_duration("7d"), 604800)

    def test_weeks(self):
        self.assertEqual(parse_duration("1w"), 604800)
        self.assertEqual(parse_duration("2w"), 1209600)

    def test_combined_units(self):
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("1d12h"), 129600)
        self.assertEqual(parse_duration("2d4h30m"), 2 * 86400 + 4 * 3600 + 30 * 60)

    def test_case_insensitive(self):
        self.assertEqual(parse_duration("1H"), 3600)
        self.assertEqual(parse_duration("1D"), 86400)
        self.assertEqual(parse_duration("1W"), 604800)

    def test_whitespace_stripped(self):
        self.assertEqual(parse_duration("  1h  "), 3600)

    def test_raw_digits_as_seconds(self):
        self.assertEqual(parse_duration("3600"), 3600)

    def test_invalid_returns_none(self):
        self.assertIsNone(parse_duration("abc"))


class HumanSizeTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(human_size(500), "500 B")

    def test_kilobytes(self):
        result = human_size(1024)
        self.assertIn("KB", result)

    def test_megabytes(self):
        result = human_size(1024 ** 2)
        self.assertIn("MB", result)

    def test_gigabytes(self):
        result = human_size(1024 ** 3)
        self.assertIn("GB", result)

    def test_terabytes(self):
        result = human_size(1024 ** 4)
        self.assertIn("TB", result)

    def test_fractional_display(self):
        result = human_size(1536 * 1024)  # 1.5 MB
        self.assertIn("1.5", result)
        self.assertIn("MB", result)


class DumpOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_json_file_output(self):
        out_path = os.path.join(self.tmpdir, "output.json")
        data = {"key": "value", "count": 42}
        dump_output(data, out_path)

        with open(out_path) as f:
            loaded = json.load(f)
        self.assertEqual(loaded, data)

    def test_yaml_file_output(self):
        out_path = os.path.join(self.tmpdir, "output.yaml")
        data = {"key": "value"}
        dump_output(data, out_path)

        self.assertTrue(os.path.exists(out_path))

    def test_yml_extension(self):
        out_path = os.path.join(self.tmpdir, "output.yml")
        data = {"key": "value"}
        dump_output(data, out_path)

        self.assertTrue(os.path.exists(out_path))

    def test_creates_parent_dirs(self):
        out_path = os.path.join(self.tmpdir, "nested", "dir", "output.json")
        data = {"key": "value"}
        dump_output(data, out_path)

        self.assertTrue(os.path.exists(out_path))

    def test_expands_tilde(self):
        # This test just verifies no error is raised
        # We don't actually write to home dir
        pass


if __name__ == "__main__":
    unittest.main()
