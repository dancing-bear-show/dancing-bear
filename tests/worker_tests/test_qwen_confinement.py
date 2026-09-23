"""Tests for worker.qwen.resolve_input_files — the input-confinement guard.

This is the security-critical case (contract.json:input_confinement); test it
hardest. All paths are built inside a TempDirMixin tmp_path fixture, never
against real repo paths.

worker.qwen does not exist in this worktree yet (impl-handler owns it, in a
parallel stage). ModuleNotFoundError here is expected.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import TempDirMixin

ALLOWLIST_DIRS = ("src", "tests", "bin", "workflows", "concerns", "docs")


class QwenConfinementBaseTests(TempDirMixin, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo_root = Path(self.tmpdir) / "repo"
        for d in ALLOWLIST_DIRS:
            (self.repo_root / d).mkdir(parents=True, exist_ok=True)
        (self.repo_root / "out").mkdir(parents=True, exist_ok=True)
        (self.repo_root / "_data").mkdir(parents=True, exist_ok=True)
        (self.repo_root / "outside").mkdir(parents=True, exist_ok=True)


class QwenConfinementRejectionTests(QwenConfinementBaseTests):
    def test_path_outside_allowlist_is_rejected_and_never_opened(self) -> None:
        """A handler that reads the file and then rejects it has already
        leaked it into memory and possibly into a log line."""
        from worker import qwen

        outside_file = self.repo_root.parent / "etc_passwd_shape"
        outside_file.write_text("root:x:0:0::/root:/bin/bash\n", encoding="utf-8")
        traversal_path = "../../etc/passwd"

        with mock.patch("builtins.open") as mock_open:
            with self.assertRaises(qwen.QwenGuardError) as ctx:
                qwen.resolve_input_files([traversal_path], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))
        mock_open.assert_not_called()

    def test_ordering_nonexistent_path_outside_allowlist_returns_confinement_error(self) -> None:
        """Proves the confinement check precedes the read: a handler that
        reads first would surface a file-not-found for this path instead,
        and would pass every other confinement test in this file."""
        from worker import qwen

        nonexistent_traversal = "../../does/not/exist/at/all"

        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen.resolve_input_files([nonexistent_traversal], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))
        self.assertNotIsInstance(ctx.exception, FileNotFoundError)

    def test_path_inside_repo_but_outside_allowlist_is_rejected(self) -> None:
        """Repo-root containment alone would admit an out/ or _data/
        artifact; the allowlist must distinguish these from the allowed
        dirs."""
        from worker import qwen

        out_artifact = self.repo_root / "out" / "generated.json"
        out_artifact.write_text("{}", encoding="utf-8")

        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen.resolve_input_files(["out/generated.json"], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))

        data_artifact = self.repo_root / "_data" / "queue.json"
        data_artifact.write_text("{}", encoding="utf-8")

        with self.assertRaises(qwen.QwenGuardError) as ctx2:
            qwen.resolve_input_files(["_data/queue.json"], self.repo_root)

        self.assertTrue(str(ctx2.exception).startswith("terminal-path-not-allowed"))

    def test_symlink_inside_root_pointing_outside_is_rejected(self) -> None:
        """The case a string-prefix check passes and a resolved check
        catches. If this test is absent, the guard is untested in the way
        that matters."""
        from worker import qwen

        target = self.repo_root.parent / "outside_target.txt"
        target.write_text("leaked content\n", encoding="utf-8")
        link = self.repo_root / "src" / "escape_link.txt"
        os.symlink(target, link)

        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen.resolve_input_files(["src/escape_link.txt"], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))

    def test_each_denylist_entry_is_rejected_even_inside_root(self) -> None:
        """A credentials.ini in the repo is still denied, even though it
        sits inside an allowlisted directory."""
        from worker import qwen

        cases = {
            "src/credentials.ini": "credentials.ini",
            "src/.env.local": ".env*",
            "src/fake_token_store.json": "*token*.json",
            "src/id_rsa": "id_rsa",
            "src/id_ed25519": "id_ed25519",
            "src/cert.pem": "*.pem",
            "src/cert.p12": "*.p12",
        }
        for rel_path, _pattern in cases.items():
            full = self.repo_root / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("secret-shaped content\n", encoding="utf-8")

            with self.assertRaises(qwen.QwenGuardError, msg=rel_path) as ctx:
                qwen.resolve_input_files([rel_path], self.repo_root)

            self.assertTrue(
                str(ctx.exception).startswith("terminal-path-not-allowed"), rel_path
            )

    def test_path_containing_git_segment_is_rejected(self) -> None:
        from worker import qwen

        git_path = self.repo_root / "src" / ".git" / "config"
        git_path.parent.mkdir(parents=True, exist_ok=True)
        git_path.write_text("[core]\n", encoding="utf-8")

        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen.resolve_input_files(["src/.git/config"], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))

    def test_file_over_size_ceiling_is_rejected(self) -> None:
        from worker import qwen

        big_file = self.repo_root / "src" / "big.py"
        with mock.patch("worker.qwen.THRESHOLDS", qwen.QwenThresholds(max_file_bytes=10), create=True):
            big_file.write_bytes(b"x" * 100)
            with self.assertRaises(qwen.QwenGuardError) as ctx:
                qwen.resolve_input_files(["src/big.py"], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))

    def test_directory_path_is_rejected(self) -> None:
        from worker import qwen

        # src/ itself is a directory, not a file.
        with self.assertRaises(qwen.QwenGuardError) as ctx:
            qwen.resolve_input_files(["src"], self.repo_root)

        self.assertTrue(str(ctx.exception).startswith("terminal-path-not-allowed"))


class QwenConfinementAcceptanceTests(QwenConfinementBaseTests):
    def test_allowed_ordinary_repo_file_is_accepted(self) -> None:
        """Proves the guard is not simply rejecting everything, which would
        pass every rejection test above."""
        from worker import qwen

        ok_file = self.repo_root / "src" / "worker" / "qwen.py"
        ok_file.parent.mkdir(parents=True, exist_ok=True)
        ok_file.write_text("# a normal repo file\n", encoding="utf-8")

        resolved = qwen.resolve_input_files(["src/worker/qwen.py"], self.repo_root)

        self.assertEqual(len(resolved), 1)
        self.assertEqual(Path(resolved[0]).resolve(), ok_file.resolve())


if __name__ == "__main__":
    unittest.main()
