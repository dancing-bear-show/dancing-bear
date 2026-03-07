"""Reusable test mixins for common testing patterns.

Mixins for capturing output, managing temp files/dirs, and other common test utilities.
These can be combined with unittest.TestCase to add functionality.
"""

from __future__ import annotations

import io
import os
import tempfile
from contextlib import contextmanager, redirect_stdout
from typing import Callable


class TempDirMixin:
    """Mixin providing a temporary directory that's cleaned up after each test.

    Usage:
        class MyTest(TempDirMixin, unittest.TestCase):
            def test_something(self):
                path = os.path.join(self.tmpdir, "file.txt")
                ...
    """

    tmpdir: str

    def setUp(self):  # noqa: N802 - unittest method name  # NOSONAR: S100 - unittest framework method
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):  # noqa: N802 - unittest method name  # NOSONAR: S100 - unittest framework method
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def in_tmpdir(self):
        """Context manager to temporarily change to tmpdir.

        Usage:
            with self.in_tmpdir():
                # code runs in tmpdir
                ...
            # back to original directory
        """
        from contextlib import contextmanager

        @contextmanager
        def _chdir():
            import os

            old_cwd = os.getcwd()
            try:
                os.chdir(self.tmpdir)
                yield
            finally:
                os.chdir(old_cwd)

        return _chdir()


class OutputCaptureMixin:
    """Mixin for capturing stdout in tests.

    Usage:
        class MyTest(OutputCaptureMixin, unittest.TestCase):
            def test_output(self):
                with self.capture_output() as buf:
                    print("test")
                self.assertIn("test", buf.getvalue())
    """

    @contextmanager
    def capture_output(self):
        """Capture stdout, yield StringIO buffer."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            yield buf

    def assert_output_contains(self, fn: Callable, *expected_strings: str, **kwargs):
        """Assert function output contains all expected strings.

        Args:
            fn: Function to call (should print to stdout)
            *expected_strings: Strings that must appear in output
            **kwargs: Keyword arguments to pass to fn
        """
        with self.capture_output() as buf:
            fn(**kwargs)
        output = buf.getvalue()
        for s in expected_strings:
            self.assertIn(s, output)


class TempFileMixin:
    """Mixin providing temp file creation helpers.

    Usage:
        class MyTest(TempFileMixin, unittest.TestCase):
            def test_file_processing(self):
                path = self.make_temp_file("content here", suffix=".txt")
                # file is automatically cleaned up after test
    """

    def setUp(self):  # noqa: N802 - unittest method name  # NOSONAR: S100 - unittest framework method
        self._temp_files = []
        super().setUp()

    def make_temp_file(self, content: str = "", suffix: str = ".txt", binary: bool = False) -> str:
        """Create a temporary file with content, track for cleanup.

        Args:
            content: File content (str or bytes if binary=True)
            suffix: File extension/suffix
            binary: If True, write in binary mode

        Returns:
            Path to created temp file
        """
        mode = "wb" if binary else "w"
        with tempfile.NamedTemporaryFile(mode=mode, delete=False, suffix=suffix) as f:
            f.write(content.encode() if binary else content)
            self._temp_files.append(f.name)
            return f.name

    def tearDown(self):  # noqa: N802 - unittest method name  # NOSONAR: S100 - unittest framework method
        for path in self._temp_files:
            if os.path.exists(path):
                os.unlink(path)
        super().tearDown()
