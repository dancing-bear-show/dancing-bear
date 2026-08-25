"""Shared builders for LocalRenderer tests.

These were duplicated across test_diagrams_pipeline.py (twice) and
test_diagrams_renderers_coverage.py. Every LocalRenderer test needs the
same two things: a renderer whose mmdc lookup is stubbed, and MagicMock
subprocess results. Both live here so the mmdc path stays fake in exactly
one place — no test may invoke the real binary, which is absent on CI.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

FAKE_MMDC = "/usr/local/bin/mmdc"


def make_renderer(timeout: int | None = None):
    """Return a LocalRenderer with shutil.which stubbed to a fake mmdc path.

    Args:
        timeout: Passed through to LocalRenderer when given; otherwise the
            renderer's own default is used.
    """
    from diagrams.renderers import LocalRenderer

    with patch("shutil.which", return_value=FAKE_MMDC):
        return LocalRenderer(timeout=timeout) if timeout is not None else LocalRenderer()


def make_failed_result(stderr: bytes = b"mmdc error output") -> MagicMock:
    """A failed subprocess result: non-zero exit carrying stderr."""
    result = MagicMock()
    result.returncode = 1
    result.stderr = stderr
    return result
