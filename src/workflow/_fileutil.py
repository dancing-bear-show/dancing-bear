"""File utilities for the workflow engine."""

from __future__ import annotations

import os
from pathlib import Path


def write_once(path: str | Path, content: bytes) -> bool:
    """Write *content* to *path* only if it does not already exist.

    Uses O_CREAT|O_EXCL to prevent overwriting. Returns True on success,
    False if the file already existed or write failed. Never raises.
    """
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False
