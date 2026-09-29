"""Tests for workflow count-sweep: shell-free sweep counting with guarded paths and a killable matcher."""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess  # nosec B404 - wraps the real Popen to inspect the argv count-sweep builds
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from workflow import _sweep_worker, sweep_count
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
        self.assertIsNone(_sweep_worker.read_text(str(self.root / "src/pipe"), sweep_count.MAX_FILE_BYTES))


class TestMatchTimeBound(_Tree):
    """The time bound interrupts a single catastrophic ``re.search``."""

    def test_nested_quantifier_is_killed_at_the_deadline(self) -> None:
        self._put("src/evil.txt", "a" * 30 + "!\n")
        start = time.monotonic()
        with patch.object(sweep_count, "MAX_SECONDS", 1.0):
            got = count_sweep("(a+)+$", ["src"], root=self.root)
        self.assertLess(time.monotonic() - start, 10)
        self.assertTrue(got.truncated)
        self.assertEqual(got.reason, "time bound reached")

    def test_partial_count_survives_the_kill(self) -> None:
        self._put("src/1-good.txt", "aaa\naaa\n")
        self._put("src/2-evil.txt", "a" * 30 + "!\n")
        with patch.object(sweep_count, "MAX_SECONDS", 1.0):
            got = count_sweep("^(a+)+$", ["src"], root=self.root)
        self.assertEqual((got.hits, got.files, got.truncated), (2, 1, True))

    def test_huge_alternation_within_the_length_cap_counts(self) -> None:
        pattern = "|".join(f"w{i}x" for i in range(100))
        self.assertLessEqual(len(pattern), sweep_count.MAX_PATTERN_CHARS)
        self._put("src/w.txt", "w7x\nw99x\nnope\n")
        self.assertEqual(count_sweep(pattern, ["src/w.txt"], root=self.root).hits, 2)

    def test_huge_alternation_over_the_length_cap_is_refused(self) -> None:
        pattern = "|".join(f"word{i}" for i in range(200))
        with self.assertRaisesRegex(SweepError, "longer than"):
            count_sweep(pattern, ["src"], root=self.root)

    def test_worker_gets_the_job_as_stdin_data_with_no_shell(self) -> None:
        # Shell-looking text as a valid regex: the escaped form matches the
        # literal characters. A shell expanding it would count "uid=" output,
        # not these two fixture lines, and the argv would carry the pattern.
        self._put("src/shell.txt", "run $(id) here\nrun `id` here\nuid=501\n")
        real_popen = subprocess.Popen
        with patch.object(sweep_count.subprocess, "Popen", side_effect=real_popen) as popen:
            got = count_sweep(r"\$\(id\)|`id`", ["src/shell.txt"], root=self.root)
        self.assertEqual((got.hits, got.files, got.truncated), (2, 1, False))
        args, kwargs = popen.call_args
        self.assertEqual(args[0][1:3], ["-I", "-S"])
        self.assertTrue(str(args[0][3]).endswith("_sweep_worker.py"))
        self.assertEqual(len(args[0]), 4)
        self.assertNotIn("shell", kwargs)

    def test_worker_crash_is_reported_as_partial_with_its_error(self) -> None:
        with patch.object(sweep_count, "_WORKER", self.root / "missing_worker.py"):
            got = count_sweep("check", ["workflows"], root=self.root)
        self.assertTrue(got.truncated)
        self.assertIn("matcher failed", got.reason)

    def test_truncated_or_garbled_worker_lines_are_ignored(self) -> None:
        got = sweep_count._parse_worker_output('{"hits": 2, "files": 1}\n{"hits": 5, "fi', fallback_reason="x")
        self.assertEqual((got.hits, got.files, got.truncated, got.reason), (2, 1, True, "x"))

    def test_deadline_is_enforced_while_walking_empty_directories(self) -> None:
        # Regression: a tree of only empty directories never yields a file, so
        # a deadline checked only after a file yields would never fire. Force
        # the deadline into the past before the walk starts so the very first
        # per-directory check in _iter_files must be what catches it.
        for i in range(5):
            (self.root / f"src/empty{i}").mkdir(parents=True)
        root_real = self.root.resolve(strict=True)
        past_deadline = time.monotonic() - 1
        with self.assertRaises(sweep_count._DeadlineExceeded):
            list(sweep_count._iter_files(root_real / "src", root_real, past_deadline))

    def test_count_sweep_reports_truncated_when_deadline_hits_during_listing(self) -> None:
        # End-to-end: count_sweep must catch _DeadlineExceeded raised from the
        # walk (not just the post-yield check) and report a truncated result
        # rather than letting the exception escape or hanging.
        for i in range(5):
            (self.root / f"src/empty{i}").mkdir(parents=True)
        real_monotonic = time.monotonic
        calls = {"n": 0}

        def fake_monotonic() -> float:
            calls["n"] += 1
            # First call establishes the deadline; every call after that
            # (inside the walk) reports time already past it.
            return real_monotonic() if calls["n"] == 1 else real_monotonic() + sweep_count.MAX_SECONDS + 1

        with patch.object(sweep_count.time, "monotonic", side_effect=fake_monotonic):
            got = sweep_count.count_sweep("check", ["src"], root=self.root)
        self.assertTrue(got.truncated)
        self.assertEqual(got.reason, "time bound reached while listing files")

    def test_deadline_not_exceeded_walks_normally(self) -> None:
        # Happy path: a normal deadline far in the future does not interfere
        # with a complete, non-truncated walk.
        root_real = self.root.resolve(strict=True)
        future_deadline = time.monotonic() + 60
        found = sorted(p.name for p in sweep_count._iter_files(root_real / "workflows", root_real, future_deadline))
        self.assertEqual(found, ["a.yaml", "b.yaml"])


class TestSweepWorker(_Tree):
    """The child's matcher, run in-process so its branches are measured.

    ``self.root`` is resolved to its canonical form here: the real pipeline
    (``sweep_count.resolve_paths``) always hands the worker a fully resolved
    path, never one through an OS-level symlink such as macOS's
    ``/var -> /private/var``, and the worker's per-component ``O_NOFOLLOW``
    reopen (see ``_open_nofollow_along_path``) depends on that being true.
    """

    def setUp(self) -> None:
        super().setUp()
        self.root = self.root.resolve(strict=True)

    def _run(self, files: list[str], **caps: int) -> list[dict[str, object]]:
        job: dict[str, object] = {"pattern": "check", "files": files, "max_file_bytes": 1_000,
                                  "max_line_chars": 100, "max_total_bytes": 10_000, **caps}
        out = io.StringIO()
        with redirect_stdout(out):
            _sweep_worker.run(job)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def test_emits_running_totals_then_done(self) -> None:
        files = [str(self.root / "workflows/a.yaml"), str(self.root / "src/c.py"), str(self.root / "workflows/sub/b.yaml")]
        self.assertEqual(self._run(files), [{"hits": 2, "files": 1}, {"hits": 3, "files": 2},
                                            {"hits": 3, "files": 2, "done": True}])

    def test_byte_bound_emits_truncated(self) -> None:
        records = self._run([str(self.root / "workflows/a.yaml")], max_total_bytes=5)
        self.assertIs(records[-1]["truncated"], True)

    def test_byte_bound_counts_bytes_not_characters(self) -> None:
        # 21 characters but 41 bytes: under a 30-unit budget by characters,
        # over it by bytes. The ASCII control of the same length stays under.
        wide = self._put("src/wide.txt", "\u00e9" * 20 + "\n")
        narrow = self._put("src/narrow.txt", "e" * 20 + "\n")
        self.assertEqual(self._run([str(wide)], max_total_bytes=30)[-1],
                         {"hits": 0, "files": 0, "truncated": True, "reason": "byte bound reached"})
        self.assertEqual(self._run([str(narrow)], max_total_bytes=30)[-1], {"hits": 0, "files": 0, "done": True})

    def test_per_file_bound_counts_bytes_not_characters(self) -> None:
        wide = self._put("src/wide.txt", "check\u00e9")  # 6 characters, 7 bytes
        self.assertEqual(self._run([str(wide)], max_file_bytes=6)[-1], {"hits": 0, "files": 0, "done": True})
        self.assertEqual(self._run([str(wide)], max_file_bytes=7)[-1], {"hits": 1, "files": 1, "done": True})

    def test_read_text_reports_raw_byte_length(self) -> None:
        got = _sweep_worker.read_text(str(self._put("src/wide.txt", "\u00e9\n")), 1_000)
        self.assertEqual((got.text, got.nbytes) if got else None, ("\u00e9\n", 3))

    def test_oversized_binary_and_missing_files_skipped(self) -> None:
        self._put("src/bin.dat", b"check\0")
        files = [str(self.root / "src/bin.dat"), str(self.root / "workflows/a.yaml"), str(self.root / "nope")]
        self.assertEqual(self._run(files, max_file_bytes=10)[-1], {"hits": 0, "files": 0, "done": True})

    def test_read_text_still_reads_a_normal_nested_file(self) -> None:
        # Happy path for the directory-relative reopen: an ordinary file several
        # components deep must still be read like a plain O_NOFOLLOW open would.
        got = _sweep_worker.read_text(str(self.root / "workflows/sub/b.yaml"), 1_000)
        self.assertEqual((got.text, got.nbytes) if got else None, ("check-params --check z\n", 23))

    def test_read_text_refuses_an_intermediate_directory_swapped_for_a_symlink(self) -> None:
        # The TOCTOU this fix closes: the parent validated the path while
        # "src" was a real directory, then something replaced "src" with a
        # symlink before the worker reopened it. A single O_NOFOLLOW on the
        # final component alone would still follow this, because only the
        # last name is checked; the component-by-component reopen must not.
        target = self._put("src/real.txt", "check\n")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "real.txt").write_text("check\n", encoding="utf-8")
        path_seen_by_worker = str(target)
        self.assertEqual(_sweep_worker.read_text(path_seen_by_worker, 1_000).text, "check\n")  # sanity: reads fine first
        shutil.rmtree(self.root / "src")
        (self.root / "src").symlink_to(outside.name)
        self.assertIsNone(_sweep_worker.read_text(path_seen_by_worker, 1_000))

    def test_open_nofollow_along_path_rejects_relative_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "not an absolute path"):
            fd = _sweep_worker._open_nofollow_along_path("workflows/a.yaml")
            os.close(fd)  # reached only if the guard regresses; never leak the descriptor


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

    def test_non_ascii_letters_refused(self) -> None:
        for bad in ("src/é", "ѕrc"):  # e-acute; Cyrillic dze, a lookalike of s
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


def _cli(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(["count-sweep", *argv])
    return code, out.getvalue(), err.getvalue()


class TestCountSweepCLI(_Tree):
    def setUp(self) -> None:
        super().setUp()
        # The CLI anchors --root to this checkout; pointing the anchor at the
        # temp tree is a test-only seam, not something the CLI exposes.
        anchor = patch.object(sweep_count, "repo_root", return_value=self.root.resolve())
        anchor.start()
        self.addCleanup(anchor.stop)

    def _run(self, *argv: str) -> tuple[int, str, str]:
        return _cli("--root", str(self.root), *argv)

    def test_symlinked_root_escaping_the_anchor_refused(self) -> None:
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        Path(outside.name, "src").mkdir()
        (self.root / "escape").symlink_to(outside.name)
        code, out, err = _cli("--root", str(self.root / "escape"), "--pattern=x", "--path", "src")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("refused root", err)

    def test_file_or_missing_root_refused(self) -> None:
        for root in (str(self.root / "src/c.py"), str(self.root / "missing")):
            with self.subTest(root=root):
                code, out, err = _cli("--root", root, "--pattern=x", "--path", "src")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("refused root", err)


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

    def test_multibyte_text_over_the_byte_budget_exits_1(self) -> None:
        self._put("src/wide.txt", "check " + "\u00e9" * 20 + "\n")  # 27 characters, 47 bytes
        with patch.object(sweep_count, "MAX_TOTAL_BYTES", 40):
            code, out, err = self._run("--pattern=check", "--path", "src/wide.txt")
        self.assertEqual(code, 1, err)
        self.assertIs(json.loads(out)["truncated"], True)
        self.assertIn("byte bound", err)


class TestCountSweepCLIRoot(unittest.TestCase):
    """``--root`` is caller text, so the CLI holds it to this checkout (no seam patched)."""

    repo = Path(sweep_count.__file__).resolve().parents[2]

    def test_repo_root_is_the_pyproject_directory(self) -> None:
        self.assertEqual(sweep_count.repo_root(), self.repo)
        self.assertTrue((self.repo / "pyproject.toml").is_file())

    def test_roots_outside_the_checkout_refused(self) -> None:
        for root in ("/", str(self.repo / ".."), str(self.repo / "src/../..")):
            with self.subTest(root=root):
                code, out, err = _cli("--root", root, "--pattern=root", "--path", "etc/passwd")
                self.assertEqual((code, out), (2, ""))
                self.assertIn("refused root", err)

    def test_relative_dotdot_refused_from_the_repo_root(self) -> None:
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.repo)
        code, out, err = _cli("--root", "..", "--pattern=x", "--path", "src")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("refused root", err)

    def test_directory_inside_the_checkout_accepted(self) -> None:
        code, out, err = _cli("--root", str(self.repo / "src"), "--pattern=def cli_root",
                              "--path", "workflow/sweep_count.py")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"hits": 1, "files": 1})

    def test_default_root_is_the_repo_root(self) -> None:
        code, out, err = _cli("--pattern=def cli_root", "--path", "src/workflow/sweep_count.py")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"hits": 1, "files": 1})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
