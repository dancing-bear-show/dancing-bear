"""Shared helpers for agent_helpers tests."""

from __future__ import annotations

import json
from pathlib import Path

from agent_helpers.cli import main
from tests.fixtures import capture_stderr, capture_stdout


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI in-process; return (exit code, stdout, stderr)."""
    with capture_stdout() as out, capture_stderr() as err:
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


def run_json(argv: list[str]) -> dict:
    """Run the CLI and parse its stdout as one JSON object; assert exit 0."""
    rc, out, err = run_main(argv)
    if rc != 0:
        raise AssertionError(f"exit {rc}: stdout={out!r} stderr={err!r}")
    return json.loads(out)


def write(directory: str, name: str, text: str) -> str:
    """Write ``text`` to ``directory/name`` and return the path."""
    path = Path(directory) / name
    path.write_text(text, encoding="utf-8")
    return str(path)
