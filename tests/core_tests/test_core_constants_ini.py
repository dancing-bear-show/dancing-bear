"""Tests for credentials INI readers in core/constants.py."""

from __future__ import annotations

import os
import tempfile
import unittest

from core.constants import (
    read_credential_ini_first,
    read_credential_ini_merged,
)


class IniTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name: str, body: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


class ReadFirstTests(IniTestBase):
    def test_returns_none_when_no_paths_exist(self):
        path, sections = read_credential_ini_first(search_paths=["/nonexistent/x.ini"])
        self.assertIsNone(path)
        self.assertEqual(sections, {})

    def test_empty_search_paths(self):
        path, sections = read_credential_ini_first(search_paths=[])
        self.assertIsNone(path)
        self.assertEqual(sections, {})

    def test_reads_first_existing_file(self):
        first = self._write("a.ini", "[mail]\ntoken = a\n")
        second = self._write("b.ini", "[mail]\ntoken = b\n")
        path, sections = read_credential_ini_first(search_paths=[first, second])
        self.assertEqual(path, first)
        self.assertEqual(sections["mail"]["token"], "a")

    def test_explicit_path_takes_precedence(self):
        explicit = self._write("explicit.ini", "[mail]\ntoken = explicit\n")
        other = self._write("other.ini", "[mail]\ntoken = other\n")
        path, sections = read_credential_ini_first(explicit, search_paths=[other])
        self.assertEqual(path, explicit)
        self.assertEqual(sections["mail"]["token"], "explicit")

    def test_skips_missing_file_and_continues(self):
        real = self._write("real.ini", "[mail]\ntoken = real\n")
        path, _ = read_credential_ini_first(
            search_paths=["/nonexistent/x.ini", real]
        )
        self.assertEqual(path, real)

    def test_require_section_skips_file_lacking_section(self):
        """An earlier file without the section must not shadow a later one."""
        empty = self._write("empty.ini", "[other]\nk = v\n")
        target = self._write("target.ini", "[musickit.personal]\ntoken = t\n")
        path, sections = read_credential_ini_first(
            search_paths=[empty, target], require_section="musickit.personal"
        )
        self.assertEqual(path, target)
        self.assertEqual(sections["musickit.personal"]["token"], "t")

    def test_require_section_returns_none_when_absent_everywhere(self):
        a = self._write("a.ini", "[other]\nk = v\n")
        path, sections = read_credential_ini_first(
            search_paths=[a], require_section="missing"
        )
        self.assertIsNone(path)
        self.assertEqual(sections, {})

    def test_without_require_section_first_file_wins(self):
        empty = self._write("empty.ini", "[other]\nk = v\n")
        target = self._write("target.ini", "[mail]\ntoken = t\n")
        path, sections = read_credential_ini_first(search_paths=[empty, target])
        self.assertEqual(path, empty)
        self.assertNotIn("mail", sections)

    def test_require_option_skips_file_lacking_key(self):
        """A creds file with the section but not the key must not shadow."""
        partial = self._write("partial.ini", "[ios_devices]\nother = x\n")
        target = self._write("target.ini", "[ios_devices]\nmyphone = UDID123\n")
        _path, sections = read_credential_ini_first(
            search_paths=[partial, target],
            require_section="ios_devices",
            require_option="myphone",
        )
        self.assertEqual(sections["ios_devices"]["myphone"], "UDID123")

    def test_require_option_returns_none_when_absent(self):
        partial = self._write("partial.ini", "[ios_devices]\nother = x\n")
        path, sections = read_credential_ini_first(
            search_paths=[partial],
            require_section="ios_devices",
            require_option="myphone",
        )
        self.assertIsNone(path)
        self.assertEqual(sections, {})

    def test_require_option_without_section_raises(self):
        with self.assertRaises(ValueError):
            read_credential_ini_first(search_paths=[], require_option="k")

    def test_expands_user_in_path(self):
        path, _ = read_credential_ini_first(search_paths=["~/definitely-not-here.ini"])
        self.assertIsNone(path)

    def test_malformed_file_is_skipped(self):
        bad = self._write("bad.ini", "not an ini [[[\nzzz\n")
        good = self._write("good.ini", "[mail]\ntoken = good\n")
        path, sections = read_credential_ini_first(search_paths=[bad, good])
        self.assertEqual(path, good)
        self.assertEqual(sections["mail"]["token"], "good")

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_unreadable_file_does_not_shadow_later_readable_one(self):
        """ConfigParser.read() ignores permission errors and returns [].

        Without checking that return value an unreadable creds file parses as
        an empty config and wins the search, hiding a valid later file.
        """
        unreadable = self._write("locked.ini", "[mail]\ntoken = locked\n")
        os.chmod(unreadable, 0o000)
        self.addCleanup(os.chmod, unreadable, 0o644)
        good = self._write("good.ini", "[mail]\ntoken = good\n")

        path, sections = read_credential_ini_first(search_paths=[unreadable, good])
        self.assertEqual(path, good)
        self.assertEqual(sections["mail"]["token"], "good")

    @unittest.skipIf(os.geteuid() == 0, "root bypasses file permissions")
    def test_merged_skips_unreadable_file(self):
        unreadable = self._write("locked.ini", "[mail]\ntoken = locked\n")
        os.chmod(unreadable, 0o000)
        self.addCleanup(os.chmod, unreadable, 0o644)
        good = self._write("good.ini", "[mail]\ntoken = good\n")

        merged = read_credential_ini_merged([unreadable, good])
        self.assertEqual(merged["mail"]["token"], "good")

    def test_values_are_not_interpolated(self):
        """Percent signs in secrets must survive verbatim."""
        p = self._write("i.ini", "[mail]\ntoken = abc%%def\n")
        _, sections = read_credential_ini_first(search_paths=[p])
        self.assertIn("%", sections["mail"]["token"])


class ReadMergedTests(IniTestBase):
    def test_empty_when_nothing_exists(self):
        self.assertEqual(
            read_credential_ini_merged(["/nonexistent/x.ini"]), {}
        )

    def test_first_path_wins_per_key(self):
        first = self._write("a.ini", "[mail]\ntoken = first\n")
        second = self._write("b.ini", "[mail]\ntoken = second\n")
        merged = read_credential_ini_merged([first, second])
        self.assertEqual(merged["mail"]["token"], "first")

    def test_later_path_supplies_missing_keys(self):
        first = self._write("a.ini", "[mail]\ntoken = first\n")
        second = self._write("b.ini", "[mail]\ntoken = second\ncredentials = c\n")
        merged = read_credential_ini_merged([first, second])
        self.assertEqual(merged["mail"]["token"], "first")
        self.assertEqual(merged["mail"]["credentials"], "c")

    def test_merges_distinct_sections(self):
        first = self._write("a.ini", "[mail]\ntoken = t\n")
        second = self._write("b.ini", "[phone]\nudid = u\n")
        merged = read_credential_ini_merged([first, second])
        self.assertEqual(merged["mail"]["token"], "t")
        self.assertEqual(merged["phone"]["udid"], "u")

    def test_malformed_file_is_skipped(self):
        bad = self._write("bad.ini", "not an ini [[[\nzzz\n")
        good = self._write("good.ini", "[mail]\ntoken = good\n")
        merged = read_credential_ini_merged([bad, good])
        self.assertEqual(merged["mail"]["token"], "good")


if __name__ == "__main__":
    unittest.main()
