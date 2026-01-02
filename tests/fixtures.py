"""Shared test fixtures and utilities.

Cross-domain helpers used across multiple test modules.
Domain-specific fixtures live in their respective directories:
- tests/mail/fixtures.py - Gmail client fakes
- tests/calendars/fixtures.py - Outlook/Calendar fakes
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess  # nosec B404
import sys
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[1]


# -----------------------------------------------------------------------------
# Path helpers
# -----------------------------------------------------------------------------


def repo_root() -> Path:
    return REPO_ROOT


def repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


def bin_path(name: str) -> Path:
    return REPO_ROOT / "bin" / name


def test_path(filename: str = "test") -> str:
    """Get a dummy path for test fixtures that don't need actual files.

    Args:
        filename: Base filename/path segment

    Returns:
        String path suitable for test mocking/validation

    Note:
        This returns a /tmp/ path but does NOT create any files.
        For tests that need actual temp files, use:
        - TempDirMixin.tmpdir
        - temp_yaml_file() context manager
        - tempfile.TemporaryDirectory()
    """
    return f"/tmp/{filename}"  # nosec B108 - test fixture path, not used for file creation


def run(cmd: Sequence[str], cwd: Optional[str] = None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test helper with cmd controlled by test code


def has_pyyaml() -> bool:
    try:
        return importlib.util.find_spec("yaml") is not None
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Output capture helpers
# -----------------------------------------------------------------------------


@contextmanager
def capture_stdout():
    """Context manager that captures stdout and yields a StringIO buffer."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        yield buf


# -----------------------------------------------------------------------------
# YAML file helpers
# -----------------------------------------------------------------------------


def write_yaml(data: dict, dir: Optional[str] = None, filename: str = "config.yaml") -> str:
    """Write a dict to a temporary YAML file, return the path."""
    import yaml

    td = dir or tempfile.mkdtemp()
    p = os.path.join(td, filename)
    with open(p, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
    return p


@contextmanager
def temp_yaml_file(data: dict, suffix: str = ".yaml"):
    """Context manager that yields a path to a temporary YAML file."""
    import yaml

    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=suffix) as tf:
        yaml.safe_dump(data, tf)
        tf.flush()
        yield tf.name
    os.unlink(tf.name)


# -----------------------------------------------------------------------------
# CSV file helpers
# -----------------------------------------------------------------------------


def write_csv(path: str, headers: List[str], rows: List[List]) -> str:
    """Write a CSV file with headers and rows.

    Args:
        path: Full path to write the CSV file
        headers: List of column header names
        rows: List of row data (each row is a list of values)

    Returns:
        The path to the written file
    """
    import csv

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    return path


def write_csv_content(path: str, content: str) -> str:
    """Write raw CSV content to a file.

    Args:
        path: Full path to write the file
        content: Raw CSV content string

    Returns:
        The path to the written file
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


@contextmanager
def temp_csv(headers: List[str], rows: List[List], suffix: str = ".csv"):
    """Context manager that yields a path to a temporary CSV file.

    Example:
        with temp_csv(["name", "value"], [["a", "1"], ["b", "2"]]) as path:
            result = parse_csv(path)
    """
    import csv

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=suffix, newline="") as tf:
        w = csv.writer(tf)
        w.writerow(headers)
        w.writerows(rows)
        tf.flush()
        yield tf.name
    os.unlink(tf.name)


# -----------------------------------------------------------------------------
# Temporary directory mixin
# -----------------------------------------------------------------------------


class TempDirMixin:
    """Mixin providing a temporary directory that's cleaned up after each test.

    Usage:
        class MyTest(TempDirMixin, unittest.TestCase):
            def test_something(self):
                path = os.path.join(self.tmpdir, "file.txt")
                ...
    """

    tmpdir: str

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
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


# -----------------------------------------------------------------------------
# JSON file helpers
# -----------------------------------------------------------------------------


@contextmanager
def temp_json_file(data: Dict[str, Any], suffix: str = ".json"):
    """Context manager that yields a path to a temporary JSON file.

    Example:
        with temp_json_file({"key": "value"}) as path:
            result = load_config(path)
    """
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=suffix, encoding="utf-8") as tf:
        json.dump(data, tf)
        tf.flush()
        yield tf.name
    os.unlink(tf.name)


# -----------------------------------------------------------------------------
# Module path helpers
# -----------------------------------------------------------------------------


@contextmanager
def temp_module_path(path: Path):
    """Context manager that temporarily adds a path to sys.path.

    Useful for importing modules from non-standard locations like bin/.

    Example:
        with temp_module_path(repo_root() / "bin"):
            import some_script
    """
    path_str = str(path)
    sys.path.insert(0, path_str)
    try:
        yield
    finally:
        if path_str in sys.path:
            sys.path.remove(path_str)


# -----------------------------------------------------------------------------
# Mock helpers
# -----------------------------------------------------------------------------


def make_mock_envelope(ok: bool = True, result: Any = None, error: Optional[str] = None):
    """Factory for creating ResultEnvelope mocks.

    This reduces boilerplate when testing pipeline code that uses ResultEnvelope.

    Args:
        ok: Whether envelope.ok() should return True
        result: The result payload (envelope.result and envelope.unwrap() return value)
        error: Optional error message (envelope.error)

    Returns:
        MagicMock configured as a ResultEnvelope

    Example:
        envelope = make_mock_envelope(ok=True, result={"labels": []})
        processor.process.return_value = envelope
    """
    envelope = MagicMock()
    envelope.ok.return_value = ok
    envelope.result = result
    envelope.error = error
    envelope.unwrap.return_value = result
    if error:
        envelope.diagnostics = {"message": error}
    else:
        envelope.diagnostics = None
    return envelope


def make_mock_processor(envelope=None, ok: bool = True, result: Any = None):
    """Factory for creating Processor mocks with a pre-configured envelope.

    Args:
        envelope: Optional pre-built envelope (if None, creates one using ok/result)
        ok: Whether the envelope should indicate success
        result: The result payload for the envelope

    Returns:
        MagicMock configured as a Processor

    Example:
        processor = make_mock_processor(ok=True, result=stats)
        with patch("module.MyProcessor", return_value=processor):
            run_command(args)
    """
    if envelope is None:
        envelope = make_mock_envelope(ok=ok, result=result)
    processor = MagicMock()
    processor.process.return_value = envelope
    return processor
