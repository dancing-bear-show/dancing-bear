"""Tests for worker.qwen.resolve_input_files, the input-confinement guard.

This is the security-critical case (contract.json:input_confinement). The
guard must reject a path BEFORE opening it: a guard that reads the file and
then rejects it has already pulled the contents into memory.

"Never opened" is enforced by _no_file_reads, which fails on every read
route rather than builtins.open alone: on Python 3.11 pathlib's read_text
and read_bytes go through io.open, which a builtins.open patch does not
intercept. Every rejection test runs under it, and the targets exist, so
a reading guard would actually have something to read.
"""

from __future__ import annotations

import contextlib
import os
import stat
import unittest
from collections.abc import Iterator
from pathlib import Path
import unittest.mock as mock

from tests.fixtures import TempDirMixin
from tests.worker_tests.qwen_fixtures import GREET_PATH, QwenHandlerCase, require
from worker import qwen

ALLOWLIST_DIRS = ("src", "tests", "bin", "workflows", "concerns", "docs")
_READ_ROUTES = (
    "builtins.open",
    "io.open",
    "os.open",
    "pathlib.Path.open",
    "pathlib.Path.read_text",
    "pathlib.Path.read_bytes",
)


@contextlib.contextmanager
def _no_file_reads() -> Iterator[None]:
    """Fail the test if anything opens a file while the context is active."""
    with contextlib.ExitStack() as stack:
        for target in _READ_ROUTES:
            stack.enter_context(mock.patch(target, side_effect=AssertionError(f"guard opened a file via {target}")))
        yield


class QwenConfinementBaseTests(TempDirMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo_root = Path(self.tmpdir) / "repo"
        for d in ALLOWLIST_DIRS:
            (self.repo_root / d).mkdir(parents=True, exist_ok=True)
        for d in ("out", "_data", "srcevil"):
            (self.repo_root / d).mkdir(parents=True, exist_ok=True)

    def _write(self, rel: str, content: str = "secret-shaped content\n") -> Path:
        path = self.repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def assert_rejected_unread(self, raw: str) -> None:
        with _no_file_reads(), self.assertRaises(qwen.QwenGuardError, msg=raw) as ctx:
            qwen.resolve_input_files([raw], self.repo_root)
        self.assertEqual(str(ctx.exception), f"terminal-path-not-allowed: {raw}")


class QwenConfinementRejectionTests(QwenConfinementBaseTests):
    def test_path_outside_allowlist_is_rejected_and_never_opened(self) -> None:
        outside = self.repo_root.parent / "etc_passwd_shape"
        outside.write_text("root:x:0:0::/root:/bin/bash\n", encoding="utf-8")

        self.assert_rejected_unread("../etc_passwd_shape")
        self.assert_rejected_unread(str(outside))

    def test_sentinel_catches_a_pathlib_read(self) -> None:
        """Proves _no_file_reads has teeth for the route the old builtins.open
        patch missed."""
        target = self._write("src/ok.py")

        with _no_file_reads(), self.assertRaises(AssertionError):
            target.read_bytes()

    def test_ordering_nonexistent_path_outside_allowlist_returns_confinement_error(self) -> None:
        """A handler that reads first would surface FileNotFoundError here."""
        self.assert_rejected_unread("../../does/not/exist/at/all")

    def test_path_inside_repo_but_outside_allowlist_is_rejected(self) -> None:
        """Repo-root containment alone would admit an out/ or _data/ artifact."""
        self._write("out/generated.json", "{}")
        self._write("_data/queue.json", "{}")

        self.assert_rejected_unread("out/generated.json")
        self.assert_rejected_unread("_data/queue.json")

    def test_sibling_directory_sharing_an_allowlist_prefix_is_rejected(self) -> None:
        """srcevil/ starts with the string 'src' but is not under src/."""
        self._write("srcevil/x.py")

        self.assert_rejected_unread("srcevil/x.py")

    def test_absolute_path_is_rejected(self) -> None:
        self.assert_rejected_unread("/etc/passwd")

    def test_symlink_inside_root_pointing_outside_is_rejected(self) -> None:
        """The case a string-prefix check passes and a resolved check catches."""
        target = self.repo_root.parent / "outside_target.txt"
        target.write_text("leaked content\n", encoding="utf-8")
        os.symlink(target, self.repo_root / "src" / "escape_link.txt")

        self.assert_rejected_unread("src/escape_link.txt")

    def _symlink_allowlist_dir(self, name: str, target: Path) -> None:
        """Replace the empty allowlist directory `name` with a symlink to target."""
        (self.repo_root / name).rmdir()
        os.symlink(target, self.repo_root / name)

    def test_allowlist_dir_symlinked_outside_the_repo_is_rejected(self) -> None:
        """src/ -> /sensitive must not move the trust boundary to /sensitive."""
        sensitive = self.repo_root.parent / "sensitive"
        sensitive.mkdir()
        (sensitive / "private.txt").write_text("leaked content\n", encoding="utf-8")
        self._symlink_allowlist_dir("src", sensitive)

        self.assert_rejected_unread("src/private.txt")
        # The post-open check applies the same policy to the kernel's path for
        # the descriptor, so it must refuse the real outside file too.
        with self.assertRaises(qwen.QwenGuardError):
            qwen._read_confined_bytes([(sensitive / "private.txt").resolve()], self.repo_root.resolve())

    def test_allowlist_dir_symlinked_inside_the_repo_is_still_accepted(self) -> None:
        """A symlinked allowlist dir that stays in the checkout is legitimate."""
        real_docs = self.repo_root / "src" / "real_docs"
        real_docs.mkdir()
        (real_docs / "guide.md").write_text("ok\n", encoding="utf-8")
        self._symlink_allowlist_dir("docs", real_docs)

        [resolved] = qwen.resolve_input_files(["docs/guide.md"], self.repo_root)
        self.assertEqual(resolved, (real_docs / "guide.md").resolve())

    def test_each_denylist_entry_is_rejected_even_inside_root(self) -> None:
        for rel in (
            "src/credentials.ini",
            "src/.env.local",
            "src/fake_token_store.json",
            "src/id_rsa",
            "src/id_ed25519",
            "src/cert.pem",
            "src/cert.p12",
        ):
            with self.subTest(path=rel):
                self._write(rel)
                self.assert_rejected_unread(rel)

    def test_denylist_matches_case_variants(self) -> None:
        """A case-insensitive volume opens cert.PEM as the same kind of file."""
        for rel in (
            "src/Credentials.ini",
            "src/.ENV",
            "src/My_Token.JSON",
            "src/ID_RSA",
            "src/cert.PEM",
            "src/bundle.P12",
        ):
            with self.subTest(path=rel):
                self._write(rel)
                self.assert_rejected_unread(rel)

    def test_unreadable_denylisted_file_is_rejected_not_permission_error(self) -> None:
        """A guard that opened the file first would raise PermissionError."""
        secret = self._write("src/credentials.ini")
        secret.chmod(0)
        try:
            with self.assertRaises(qwen.QwenGuardError):
                qwen.resolve_input_files(["src/credentials.ini"], self.repo_root)
        finally:
            secret.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_path_containing_git_segment_is_rejected(self) -> None:
        self._write("src/.git/config", "[core]\n")
        self._write("src/.GIT/HEAD", "ref\n")

        self.assert_rejected_unread("src/.git/config")
        self.assert_rejected_unread("src/.GIT/HEAD")

    def test_file_over_size_ceiling_is_rejected(self) -> None:
        (self.repo_root / "src" / "big.py").write_bytes(b"x" * 100)

        with mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(max_file_bytes=10)):
            self.assert_rejected_unread("src/big.py")

    def test_directory_path_is_rejected(self) -> None:
        self.assert_rejected_unread("src")

    def test_first_violation_stops_before_later_paths(self) -> None:
        self._write("src/ok.py")

        with mock.patch("worker.qwen._validate_one_input_file", wraps=qwen._validate_one_input_file) as validate:
            with self.assertRaises(qwen.QwenGuardError):
                qwen.resolve_input_files(["../x", "src/ok.py"], self.repo_root)

        self.assertEqual(validate.call_count, 1)


class QwenConfinementAcceptanceTests(QwenConfinementBaseTests):
    def test_allowed_ordinary_repo_file_is_accepted(self) -> None:
        """Proves the guard is not simply rejecting everything."""
        ok_file = self._write("src/worker/qwen.py", "# a normal repo file\n")

        with _no_file_reads():
            resolved = qwen.resolve_input_files(["src/worker/qwen.py"], self.repo_root)

        self.assertEqual(resolved, [ok_file.resolve()])

    def test_every_allowlisted_directory_is_accepted(self) -> None:
        for d in ALLOWLIST_DIRS:
            with self.subTest(directory=d):
                ok_file = self._write(f"{d}/file.txt", "ok\n")
                self.assertEqual(qwen.resolve_input_files([f"{d}/file.txt"], self.repo_root), [ok_file.resolve()])


_OUTSIDE_CONTENT = "CONTENT-FROM-OUTSIDE-THE-REPO\n"


class QwenConfinementDescriptorTests(QwenConfinementBaseTests):
    """Check-then-open: a path swapped after resolve_input_files approved it.

    The read must validate the descriptor it actually opened, so each test
    approves a legitimate file, swaps something else in under that path,
    and requires the read to be rejected without the swapped-in bytes.
    """

    def _approve(self, rel: str) -> tuple[Path, Path]:
        """Write rel, run the pre-open check on it, and return (file, resolved)."""
        target = self._write(rel, "legitimate\n")
        [resolved] = qwen.resolve_input_files([rel], self.repo_root)
        return target, resolved

    def _outside_file(self, name: str = "outside_secret.txt") -> Path:
        outside = self.repo_root.parent / name
        outside.write_text(_OUTSIDE_CONTENT, encoding="utf-8")
        return outside

    def assert_read_rejected(self, resolved: Path) -> None:
        with self.assertRaises(qwen.QwenGuardError) as ctx:
            contents = qwen._read_confined_bytes([resolved], self.repo_root.resolve())
            self.fail(f"read returned {contents!r}")
        self.assertEqual(str(ctx.exception), f"terminal-path-not-allowed: {resolved}")

    def test_approved_file_reads_through_its_descriptor(self) -> None:
        _, resolved = self._approve("src/ok.py")

        self.assertEqual(qwen._read_confined_bytes([resolved], self.repo_root.resolve()), {str(resolved): b"legitimate\n"})

    def test_file_swapped_for_a_symlink_after_the_check_is_rejected(self) -> None:
        target, resolved = self._approve("src/ok.py")
        target.unlink()
        os.symlink(self._outside_file(), target)

        self.assert_read_rejected(resolved)

    def test_parent_directory_swapped_for_a_symlink_after_the_check_is_rejected(self) -> None:
        """O_NOFOLLOW only guards the last component; the descriptor's own
        path must be checked to catch an intermediate directory swap."""
        target, resolved = self._approve("src/pkg/mod.py")
        outside_dir = self.repo_root.parent / "outside_pkg"
        outside_dir.mkdir()
        (outside_dir / "mod.py").write_text(_OUTSIDE_CONTENT, encoding="utf-8")
        target.unlink()
        target.parent.rmdir()
        os.symlink(outside_dir, target.parent)

        self.assert_read_rejected(resolved)

    def test_fifo_swapped_in_after_the_check_is_rejected_without_hanging(self) -> None:
        target, resolved = self._approve("src/ok.py")
        target.unlink()
        os.mkfifo(target)

        self.assert_read_rejected(resolved)

    def test_file_grown_past_the_cap_after_the_check_is_rejected(self) -> None:
        target, resolved = self._approve("src/ok.py")
        target.write_bytes(b"x" * 100)

        with mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(max_file_bytes=20)):
            self.assert_read_rejected(resolved)

    def test_platform_without_a_descriptor_path_fails_closed(self) -> None:
        _, resolved = self._approve("src/ok.py")

        with mock.patch("worker.qwen._fd_real_path", return_value=None):
            self.assert_read_rejected(resolved)


class QwenInputFileBoundTests(QwenHandlerCase):
    """payload.files is capped before any path is touched, and duplicate
    spellings of one file collapse to a single read."""

    def test_repeated_paths_over_the_cap_are_rejected_without_any_file_access(self) -> None:
        payload: dict[str, object] = {"files": [GREET_PATH] * 10_000, "instruction": "x"}
        expected = f"terminal-invalid-payload: files must list at most {qwen.THRESHOLDS.max_input_files} entries"

        with _no_file_reads(), self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen._validate_payload(payload)
        self.assertEqual(str(ctx.exception), expected)

        with mock.patch("worker.qwen._resolve_real_path", side_effect=AssertionError("resolved a path")):
            self.assertEqual(self.run_handler({"files": [GREET_PATH] * 10_000}), (False, expected))
        self.assertEqual(self.generate_requests(), [])

    def test_cap_boundary(self) -> None:
        cap = qwen.THRESHOLDS.max_input_files
        with _no_file_reads():
            qwen._validate_payload({"files": [GREET_PATH] * cap, "instruction": "x"})
            with self.assertRaises(qwen.QwenGuardError):
                qwen._validate_payload({"files": [GREET_PATH] * (cap + 1), "instruction": "x"})

    def test_duplicate_spellings_collapse_to_one_read(self) -> None:
        spellings = [GREET_PATH, f"./{GREET_PATH}", GREET_PATH, "src/example/../example/greet.py"]
        greet = (self.repo_root / GREET_PATH).resolve()

        with mock.patch("worker.qwen._read_open_confined", wraps=qwen._read_open_confined) as read:
            ok, _ = self.run_handler({"files": spellings})

        self.assertTrue(ok)
        self.assertEqual(read.call_count, 1)
        [(_, body, _)] = self.generate_requests()
        self.assertEqual(str(require(body)["prompt"]).count(f"--- {greet} ---"), 1)
        self.assertEqual(qwen.resolve_input_files(spellings, self.repo_root), [greet])


class QwenConfinementDescriptorHandlerTests(QwenHandlerCase):
    def test_swap_after_the_check_never_reaches_the_model(self) -> None:
        outside = Path(self.tmpdir) / "outside_secret.txt"
        outside.write_text(_OUTSIDE_CONTENT, encoding="utf-8")
        greet = self.repo_root / GREET_PATH
        real_resolve = qwen.resolve_input_files

        def resolve_then_swap(files: list[str], repo_root: Path) -> list[Path]:
            resolved = real_resolve(files, repo_root)
            greet.unlink()
            os.symlink(outside, greet)
            return resolved

        with mock.patch("worker.qwen.resolve_input_files", side_effect=resolve_then_swap):
            ok, out = self.run_handler()

        self.assertFalse(ok)
        self.assertTrue(str(out).startswith("terminal-path-not-allowed: "), out)
        self.assertEqual(self.generate_requests(), [])


if __name__ == "__main__":
    unittest.main()
