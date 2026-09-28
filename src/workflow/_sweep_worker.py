"""Child process for ``workflow count-sweep``: match one pattern over a file list.

A single ``re.search`` cannot be interrupted from inside the process that runs
it, so a catastrophic pattern such as ``(a+)+$`` would ignore any in-process
time bound. :mod:`workflow.sweep_count` therefore runs this file as a separate
interpreter (``python3 -I -S <this file>``) and kills it at the deadline.

Input is one JSON object on stdin, never argv or a shell: ``pattern``,
``files`` (paths the parent already validated), and the ``max_*`` caps.
Output is one JSON line per file that had a hit, carrying the running totals,
then a final line with ``"done": true`` or ``"truncated": true``. The parent
keeps the last line it received, so a killed run still reports its partial
count.

Standard library only, and no import of the repository: ``-I`` leaves the
repository off ``sys.path`` on purpose.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from typing import Any

_BINARY_SNIFF = 8192


def read_text(path: str, max_file_bytes: int) -> str | None:
    """Return a file's text, or None for a binary, oversized, non-regular or unreadable file.

    The open refuses a symlink and never blocks, and ``fstat`` re-checks the
    opened file, so a file swapped for a FIFO or link after the parent's
    ``lstat`` is still skipped.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        try:
            info = os.fstat(fh.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_file_bytes:
                return None
            data = fh.read(max_file_bytes + 1)
        except OSError:
            return None
    if len(data) > max_file_bytes or b"\0" in data[:_BINARY_SNIFF]:
        return None
    return data.decode("utf-8", errors="replace")


def _emit(record: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def run(job: dict[str, Any]) -> None:
    """Count matching lines over ``job["files"]``, emitting running totals."""
    regex = re.compile(job["pattern"])
    max_line = int(job["max_line_chars"])
    max_total = int(job["max_total_bytes"])
    max_file = int(job["max_file_bytes"])
    hits = files = total = 0
    for path in job["files"]:
        text = read_text(path, max_file)
        if text is None:
            continue
        total += len(text)
        if total > max_total:
            _emit({"hits": hits, "files": files, "truncated": True, "reason": "byte bound reached"})
            return
        n = sum(1 for line in text.splitlines() if regex.search(line[:max_line]))
        if n:
            hits += n
            files += 1
            _emit({"hits": hits, "files": files})
    _emit({"hits": hits, "files": files, "done": True})


if __name__ == "__main__":  # pragma: no cover - exercised through sweep_count's subprocess
    run(json.load(sys.stdin))
