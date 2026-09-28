"""Tests for workflow count-sweep: in-process sweep counting with guarded paths."""

from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

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

    def _outside(self) -> Path:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "secret.txt").write_text("check\n", encoding="utf-8")
        return Path(outside.name)

    def test_intermediate_symlink_to_outside_is_refused(self) -> None:
        (self.root / "src/out").symlink_to(self._outside())
        with self.assertRaisesRegex(SweepError, r"refused path \(symlink\)"):
            count_sweep("check", ["src/out/secret.txt"], root=self.root)

    def test_intermediate_symlink_inside_repo_is_refused(self) -> None:
        # Documented choice: a symlink component is refused even when it
        # stays in the repo, matching the walk, which never follows one.
        (self.root / "src/alias").symlink_to(self.root / "workflows")
        with self.assertRaisesRegex(SweepError, r"refused path \(symlink\)"):
            count_sweep("check", ["src/alias/a.yaml"], root=self.root)
        with self.assertRaisesRegex(SweepError, r"refused path \(symlink\)"):
            count_sweep("check", ["src/alias"], root=self.root)

    def test_walk_skips_in_repo_symlinked_dir(self) -> None:
        (self.root / "src/alias").symlink_to(self.root / "workflows")
        self.assertEqual(count_sweep("check", ["src"], root=self.root).hits, 0)

    def test_symlink_loop_is_refused(self) -> None:
        (self.root / "src/loop").symlink_to(self.root / "src/loop")
        with self.assertRaisesRegex(SweepError, "no such file"):
            count_sweep("check", ["src/loop"], root=self.root)
        self.assertEqual(count_sweep("check", ["src"], root=self.root).hits, 0)

    def test_root_reached_through_a_symlink_still_works(self) -> None:
        # The root itself may sit behind a symlink (macOS /var -> /private/var);
        # only components below it are checked.
        link_parent = tempfile.TemporaryDirectory()
        self.addCleanup(link_parent.cleanup)
        linked_root = Path(link_parent.name, "repo")
        linked_root.symlink_to(self.root)
        self.assertEqual(count_sweep("check", ["workflows"], root=linked_root).hits, 3)

    def test_invalid_empty_and_oversized_patterns(self) -> None:
        for bad, msg in (("(", "invalid pattern"), ("", "empty"),
                         ("it's", "single quote"), ("a\nb", "newline"),
                         ("a" * (sweep_count.MAX_PATTERN_CHARS + 1), "longer than")):
            with self.subTest(pattern=bad[:10]), self.assertRaisesRegex(SweepError, msg):
                count_sweep(bad, ["src"], root=self.root)

    def test_binary_and_oversized_files_skipped(self) -> None:
        self._put("src/bin.dat", b"check\0check\n")
        self._put("src/big.txt", "check\n")
        with patch.object(sweep_count, "MAX_FILE_BYTES", 5):
            got = count_sweep("check", ["src"], root=self.root)
        self.assertEqual(got.hits, 0)

    def test_total_byte_bound_truncates(self) -> None:
        with patch.object(sweep_count, "MAX_TOTAL_BYTES", 10):
            got = count_sweep("check", ["workflows"], root=self.root)
        self.assertTrue(got.truncated)
        self.assertIs(got.as_dict()["truncated"], True)

    def test_long_lines_matched_on_their_prefix_only(self) -> None:
        self._put("src/long.txt", "x" * sweep_count.MAX_LINE_CHARS + "check\n")
        self.assertEqual(count_sweep("check", ["src/long.txt"], root=self.root).hits, 0)


class TestSpecialFiles(_Tree):
    """Only regular files are read; anything else is skipped before it is opened."""

    def _sweep_with_timeout(self, paths: list[str], seconds: float = 10.0) -> sweep_count.SweepCount:
        # A regression that opens a FIFO blocks forever; run in a daemon
        # thread so it fails this test instead of hanging the suite.
        results: list[sweep_count.SweepCount] = []
        errors: list[SweepError] = []

        def run() -> None:
            try:
                results.append(count_sweep("check", paths, root=self.root))
            except SweepError as exc:
                errors.append(exc)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(seconds)
        self.assertFalse(worker.is_alive(), "count_sweep blocked on a special file")
        if errors:
            raise errors[0]
        return results[0]

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no mkfifo on this platform")
    def test_fifo_in_a_walked_dir_is_skipped_without_blocking(self) -> None:
        self._put("src/real.txt", "check\n")
        os.mkfifo(self.root / "src/pipe")
        got = self._sweep_with_timeout(["src"])
        self.assertEqual((got.hits, got.files), (1, 1))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no mkfifo on this platform")
    def test_fifo_named_directly_is_refused(self) -> None:
        os.mkfifo(self.root / "src/pipe")
        with self.assertRaisesRegex(SweepError, "not a regular file"):
            self._sweep_with_timeout(["src/pipe"])

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "no AF_UNIX sockets on this platform")
    def test_socket_in_a_walked_dir_is_skipped(self) -> None:
        self._put("src/real.txt", "check\n")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(sock.close)
        try:
            sock.bind(str(self.root / "src/s.sock"))
        except OSError as exc:  # path too long for sun_path on some hosts
            self.skipTest(f"cannot bind a unix socket here: {exc}")
        got = self._sweep_with_timeout(["src"])
        self.assertEqual((got.hits, got.files), (1, 1))

    @unittest.skipUnless(Path("/dev/null").exists(), "no /dev/null")
    def test_device_named_directly_is_refused(self) -> None:
        with self.assertRaisesRegex(SweepError, "not a regular file"):
            count_sweep("check", ["null"], root=Path("/dev"))

    def test_unreadable_file_is_skipped(self) -> None:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root can read a mode-000 file")
        locked = self._put("src/locked.txt", "check\n")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o600)
        self._put("src/open.txt", "check\n")
        self.assertEqual(count_sweep("check", ["src"], root=self.root).hits, 1)

    def test_empty_file_counts_zero(self) -> None:
        self._put("src/empty.txt", "")
        self.assertEqual(count_sweep("check", ["src/empty.txt"], root=self.root).as_dict(), {"hits": 0, "files": 0})

    def test_file_swapped_for_a_fifo_after_the_walk_is_not_read(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo on this platform")
        os.mkfifo(self.root / "src/pipe")
        # Simulates the race: the walk saw a regular file, the open meets a FIFO.
        self.assertIsNone(sweep_count._read_text(self.root / "src/pipe"))


class TestPathAllowlist(_Tree):
    """Each path form outside ``[A-Za-z0-9_][A-Za-z0-9._/-]*`` is refused before any IO."""

    def _refused(self, raw: str, reason: str) -> None:
        with self.assertRaisesRegex(SweepError, rf"refused path \({reason}\)"):
            count_sweep("check", [raw], root=self.root)

    def test_command_substitution_refused(self) -> None:
        self._refused("src/$(id)", "unsafe-path")
        self._refused("src/`id`", "unsafe-path")

    def test_variable_expansion_refused(self) -> None:
        self._refused("src/$HOME", "unsafe-path")

    def test_command_separators_refused(self) -> None:
        for bad in ("src;id", "src|id", "src&id", "src&&id"):
            with self.subTest(path=bad):
                self._refused(bad, "unsafe-path")

    def test_whitespace_refused(self) -> None:
        for bad in ("src id", " src", "src "):
            with self.subTest(path=bad):
                self._refused(bad, "unsafe-path")

    def test_control_characters_and_newlines_refused(self) -> None:
        for bad in ("src\tid", "src\nid", "src\x00"):
            with self.subTest(path=bad):
                self._refused(bad, "escapes-repo")

    def test_quotes_refused(self) -> None:
        for bad in ("src'x", 'src"x'):
            with self.subTest(path=bad):
                self._refused(bad, "unsafe-path")

    def test_leading_dash_refused(self) -> None:
        self._refused("-rf", "unsafe-path")

    def test_leading_dot_and_dot_segments_refused(self) -> None:
        for bad in (".hidden", "src/./c.py", "./src"):
            with self.subTest(path=bad):
                self._refused(bad, "unsafe-path")

    def test_escape_and_protected_reasons_keep_their_codes(self) -> None:
        self._refused("../x", "escapes-repo")
        self._refused("/etc", "escapes-repo")
        self._refused(".git", "protected-path")

    def test_refusal_happens_before_any_filesystem_access(self) -> None:
        missing = self.root / "does-not-exist"
        with patch.object(sweep_count.os, "walk", side_effect=AssertionError("walked")), \
                self.assertRaisesRegex(SweepError, "unsafe-path"):
            # The first path is valid and would be looked up if paths were
            # checked one at a time; the refusal must come first.
            count_sweep("check", ["src", "src;id"], root=missing)

    def test_allowlisted_forms_accepted(self) -> None:
        for good in ("src", "src/", "src/c.py", "workflows/sub", "_x"):
            with self.subTest(path=good):
                self.assertEqual(sweep_count.check_path(good), good.rstrip("/"))


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
                          (("--pattern=x", "--path", ".claude"), "protected-path"),
                          (("--pattern=x", "--path=src/$(id)"), "unsafe-path"),
                          (("--pattern=x", "--path=-src"), "unsafe-path"),
                          (("--pattern=x", "--path=src;id"), "unsafe-path")):
            with self.subTest(argv=argv):
                code, out, err = self._run(*argv)
                self.assertEqual((code, out), (2, ""))
                self.assertIn(msg, err)

    def test_truncated_scan_exits_1_with_partial_count(self) -> None:
        with patch.object(sweep_count, "MAX_TOTAL_BYTES", 10):
            code, out, err = self._run("--pattern=check", "--path", "workflows")
        self.assertEqual(code, 1)
        self.assertTrue(json.loads(out)["truncated"])
        self.assertIn("partial", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
