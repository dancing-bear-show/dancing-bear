"""Shared test fixtures and utilities.

Cross-domain helpers used across multiple test modules.
Domain-specific fixtures live in their respective directories:
- tests/mail/fixtures.py - Gmail client fakes
- tests/calendars/fixtures.py - Outlook/Calendar fakes
"""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import List, Optional, Sequence

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


def run(cmd: Sequence[str], cwd: Optional[str] = None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # noqa: S603


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
