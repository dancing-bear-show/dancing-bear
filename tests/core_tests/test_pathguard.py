"""Tests for core.pathguard and the write helpers that use it.

The defect being guarded is silent: `Path(MagicMock())` succeeds, stringifying
the mock into its own repr, and `.parent.mkdir(parents=True)` then creates a
directory named after it. So these tests assert on the filesystem as well as on
the exception — a guard that raised but still created the directory would be
useless, and only the directory check catches that.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, NonCallableMock

from core.fileutil import atomic_write_json
from core.pathguard import require_path
from core.textio import write_text


class TestRequirePathAcceptsRealPaths(unittest.TestCase):
    """The guard must not reject the values callers legitimately pass."""

    def test_accepts_str(self) -> None:
        self.assertEqual(require_path("a/b.json"), Path("a/b.json"))

    def test_accepts_absolute_path(self) -> None:
        self.assertEqual(require_path(Path("/var/data/x")), Path("/var/data/x"))

    def test_accepts_relative_path(self) -> None:
        self.assertEqual(require_path(Path("rel/file.txt")), Path("rel/file.txt"))

    def test_accepts_custom_pathlike(self) -> None:
        """A real __fspath__ implementation is a legitimate path, not a mock."""

        class Wrapper:
            def __fspath__(self) -> str:
                return "/var/data/wrapped"

        self.assertEqual(require_path(Wrapper()), Path("/var/data/wrapped"))


class TestRequirePathRejectsMocks(unittest.TestCase):
    """Every mock class from unittest.mock must be refused."""

    def test_rejects_magicmock_attribute(self) -> None:
        """The exact shape that created MagicMock/mock.log_path on disk."""
        with self.assertRaises(TypeError) as ctx:
            require_path(MagicMock().log_path)
        self.assertIn("mock", str(ctx.exception).lower())

    def test_rejects_each_mock_class(self) -> None:
        for factory in (MagicMock, Mock, AsyncMock, NonCallableMock):
            with self.subTest(mock_class=factory.__name__):
                with self.assertRaises(TypeError):
                    require_path(factory())

    def test_error_names_the_argument(self) -> None:
        with self.assertRaises(TypeError) as ctx:
            require_path(MagicMock(), argument="out_path")
        self.assertIn("out_path", str(ctx.exception))

    def test_error_names_the_mock_type(self) -> None:
        with self.assertRaises(TypeError) as ctx:
            require_path(AsyncMock())
        self.assertIn("AsyncMock", str(ctx.exception))


class TestRequirePathRejectsOtherJunk(unittest.TestCase):
    def test_rejects_none_int_and_list(self) -> None:
        for value in (None, 42, ["a"], {"p": 1}):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    require_path(value)


class TestWriteHelpersRejectMocks(unittest.TestCase):
    """The guard must hold at the helpers, and create nothing when it fires."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self._cwd = os.getcwd()
        # The junk directory is created relative to the CWD, so run in a temp
        # one — otherwise a regression would litter the checkout, which is
        # exactly how the original went unnoticed.
        os.chdir(self.tmpdir)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def test_atomic_write_json_rejects_mock(self) -> None:
        with self.assertRaises(TypeError):
            atomic_write_json(MagicMock().out_path, {"a": 1})

    def test_atomic_write_json_creates_no_junk_directory(self) -> None:
        """A guard that raised *after* the mkdir would still leave the mess."""
        with self.assertRaises(TypeError):
            atomic_write_json(MagicMock().out_path, {"a": 1})
        self.assertFalse(
            (self.tmpdir / "MagicMock").exists(),
            "guard raised but the mock-named directory was still created",
        )

    def test_write_text_rejects_mock(self) -> None:
        with self.assertRaises(TypeError):
            write_text(MagicMock().log_path, "content")

    def test_write_text_creates_no_junk_directory(self) -> None:
        with self.assertRaises(TypeError):
            write_text(MagicMock().log_path, "content")
        self.assertFalse((self.tmpdir / "MagicMock").exists())


class TestWriteHelpersStillWork(unittest.TestCase):
    """The guard must not have broken the real behaviour of either helper."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_atomic_write_json_writes_and_creates_parents(self) -> None:
        target = self.tmpdir / "nested" / "deeper" / "data.json"
        atomic_write_json(target, {"key": "value"})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"key": "value"})

    def test_atomic_write_json_accepts_a_str_path(self) -> None:
        target = self.tmpdir / "from_str.json"
        atomic_write_json(str(target), [1, 2, 3])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), [1, 2, 3])

    def test_write_text_writes_and_creates_parents(self) -> None:
        target = self.tmpdir / "nested" / "out.txt"
        write_text(target, "hello")
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")


if __name__ == "__main__":
    unittest.main()
