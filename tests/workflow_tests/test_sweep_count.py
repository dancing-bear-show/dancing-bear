"""Tests for workflow count-sweep: in-process sweep counting with guarded paths."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from workflow import sweep_count
from workflow.cli import main
from workflow.sweep_count import SweepError, count_sweep


class _Tree(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self._put("workflows/a.yaml", "check-params --check x\nnothing\ncheck-params --check y\n")
        self._put("workflows/sub/b.yaml", "check-params --check z\n")
        self._put("src/c.py", "no match here\n")

    def _put(self, rel: str, text: str | bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path


class TestCountSweep(_Tree):
    def test_counts_matching_lines_and_files(self) -> None:
        got = count_sweep(r"check-params[^|]*--check", ["workflows/", "src"], root=self.root)
        self.assertEqual((got.hits, got.files, got.truncated), (3, 2, False))
        self.assertEqual(got.as_dict(), {"hits": 3, "files": 2})

    def test_single_file_and_overlapping_paths_count_once(self) -> None:
        got = count_sweep("check", ["workflows", "workflows/a.yaml"], root=self.root)
        self.assertEqual((got.hits, got.files), (3, 2))

    def test_zero_hits_is_a_result(self) -> None:
        self.assertEqual(count_sweep("absent", ["src"], root=self.root).as_dict(), {"hits": 0, "files": 0})

    def test_refused_paths(self) -> None:
        self._put(".git/config", "check\n")
        self._put(".claude/settings.json", "check\n")
        for bad in ("../x", "workflows/../../etc", "/etc", "~/x", ".git/config", "src/.GIT",
                    ".claude/settings.json", ".github/w.yml", ".", ""):
            with self.subTest(path=bad), self.assertRaisesRegex(SweepError, "refused path"):
                count_sweep("check", [bad], root=self.root)

    def test_missing_path_and_no_paths_refused(self) -> None:
        with self.assertRaisesRegex(SweepError, "no such file"):
            count_sweep("check", ["docs"], root=self.root)
        with self.assertRaisesRegex(SweepError, "no --path"):
            count_sweep("check", [], root=self.root)

    def test_symlinks_are_not_followed(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "secret.txt").write_text("check\n", encoding="utf-8")
        (self.root / "src/link").symlink_to(outside.name)
        (self.root / "src/filelink.txt").symlink_to(Path(outside.name, "secret.txt"))
        self.assertEqual(count_sweep("check", ["src"], root=self.root).hits, 0)
        with self.assertRaisesRegex(SweepError, "symlinks are refused"):
            count_sweep("check", ["src/link"], root=self.root)

    def test_invalid_empty_and_oversized_patterns(self) -> None:
        for bad, msg in (("(", "invalid pattern"), ("", "empty"),
                         ("it's", "single quote"), ("a\nb", "newline"),
                         ("a" * (sweep_count.MAX_PATTERN_CHARS + 1), "longer than")):
            with self.subTest(pattern=bad[:10]), self.assertRaisesRegex(SweepError, msg):
                count_sweep(bad, ["src"], root=self.root)

    def test_binary_and_oversized_files_skipped(self) -> None:
        self._put("src/bin.dat", b"check\0check\n")
        self._put("src/big.txt", "check\n")
        with mock.patch.object(sweep_count, "MAX_FILE_BYTES", 5):
            got = count_sweep("check", ["src"], root=self.root)
        self.assertEqual(got.hits, 0)

    def test_total_byte_bound_truncates(self) -> None:
        with mock.patch.object(sweep_count, "MAX_TOTAL_BYTES", 10):
            got = count_sweep("check", ["workflows"], root=self.root)
        self.assertTrue(got.truncated)
        self.assertIs(got.as_dict()["truncated"], True)

    def test_long_lines_matched_on_their_prefix_only(self) -> None:
        self._put("src/long.txt", "x" * sweep_count.MAX_LINE_CHARS + "check\n")
        self.assertEqual(count_sweep("check", ["src/long.txt"], root=self.root).hits, 0)


class TestCountSweepCLI(_Tree):
    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["count-sweep", "--root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_prints_hits_json(self) -> None:
        code, out, _ = self._run("--pattern=check-params[^|]*--check", "--path", "workflows/", "--path", "src")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"hits": 3, "files": 2})

    def test_pattern_starting_with_dash_works_in_equals_form(self) -> None:
        code, out, _ = self._run("--pattern=--check", "--path", "workflows")
        self.assertEqual((code, json.loads(out)["hits"]), (0, 3))

    def test_invalid_pattern_and_refused_path_exit_2(self) -> None:
        for argv, msg in ((("--pattern=(", "--path", "src"), "invalid pattern"),
                          (("--pattern=x", "--path", "../etc"), "escapes-repo"),
                          (("--pattern=x", "--path", "/etc"), "escapes-repo"),
                          (("--pattern=x", "--path", ".git"), "protected-path"),
                          (("--pattern=it's", "--path", "src"), "single quote"),
                          (("--pattern=x", "--path", ".claude"), "protected-path")):
            with self.subTest(argv=argv):
                code, out, err = self._run(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(msg, err)

    def test_truncated_scan_exits_1_with_partial_count(self) -> None:
        with mock.patch.object(sweep_count, "MAX_TOTAL_BYTES", 10):
            code, out, err = self._run("--pattern=check", "--path", "workflows")
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(out)["truncated"])
        self.assertIn("partial", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
