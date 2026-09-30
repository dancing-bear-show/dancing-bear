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
from dataclasses import dataclass
from typing import Any

_BINARY_SNIFF = 8192


@dataclass(frozen=True)
class FileText:
    """A file's decoded text and the byte length it was decoded from."""

    text: str
    #: Raw size on disk; the byte bounds count this, never ``len(text)``,
    #: which is characters and undercounts multibyte UTF-8.
    nbytes: int


def _open_nofollow_along_path(path: str) -> int:
    """Open ``path`` by walking it one component at a time, each ``O_NOFOLLOW``.

    A single ``os.open(path, O_NOFOLLOW)`` only refuses a symlink in the final
    component: the kernel still resolves every earlier component by name, so a
    directory swapped for a symlink between the parent's validation and this
    open still lets the open escape through it. Opening each component with
    ``dir_fd`` set to its *already-open* parent closes that window: once a
    directory is open, further opens beneath it resolve against that open
    inode, not against a name that could be re-pointed afterward.

    ``path`` must be absolute; the parent only ever sends absolute, fully
    resolved paths (see :mod:`workflow.sweep_count`), and treating a relative
    one as root-relative here would silently look in the wrong place.
    """
    if not os.path.isabs(path):
        raise ValueError(f"not an absolute path: {path!r}")
    parts = [p for p in path.split(os.sep) if p]
    if not parts:
        raise ValueError(f"no such file or directory: {path!r}")
    dir_fd = os.open(os.sep, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = next_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        return os.open(parts[-1], flags, dir_fd=dir_fd)
    finally:
        os.close(dir_fd)


def read_text(path: str, max_file_bytes: int) -> FileText | None:
    """Return a file's text, or None for a binary, oversized, non-regular or unreadable file.

    Every path component, not just the last, is opened ``O_NOFOLLOW`` and
    relative to its already-open parent (see :func:`_open_nofollow_along_path`),
    so a directory swapped for a symlink after the parent process validated
    this path is still refused rather than silently followed. ``fstat``
    re-checks the opened file, so a file swapped for a FIFO or link after the
    parent's ``lstat`` is still skipped.
    """
    try:
        fd = _open_nofollow_along_path(path)
    except (OSError, ValueError, NotImplementedError):
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
    return FileText(data.decode("utf-8", errors="replace"), len(data))


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
        read = read_text(path, max_file)
        if read is None:
            continue
        total += read.nbytes  # bytes, like max_file_bytes; not len(read.text)
        if total > max_total:
            _emit({"hits": hits, "files": files, "truncated": True, "reason": "byte bound reached"})
            return
        # The line cap is characters by design: it bounds what one re.search
        # sees, and slicing by bytes could split a UTF-8 sequence.
        n = sum(1 for line in read.text.splitlines() if regex.search(line[:max_line]))
        if n:
            hits += n
            files += 1
            _emit({"hits": hits, "files": files})
    _emit({"hits": hits, "files": files, "done": True})


if __name__ == "__main__":  # pragma: no cover - exercised through sweep_count's subprocess
    run(json.load(sys.stdin))
