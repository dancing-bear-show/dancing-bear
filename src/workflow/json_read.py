"""Read a JSON file, classifying failure so each caller can word its own error."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path


class JsonReadFailure(StrEnum):
    MISSING = "missing"
    UNREADABLE = "unreadable"  # OSError other than missing, or bytes that are not UTF-8
    INVALID = "invalid"  # readable text that is not valid JSON


class JsonReadError(Exception):
    """A JSON file could not be loaded; ``cause`` is the underlying exception."""

    def __init__(self, kind: JsonReadFailure, path: Path, cause: Exception) -> None:
        super().__init__(f"{path}: {kind}: {cause}")
        self.kind = kind
        self.path = path
        self.cause = cause

    @property
    def detail(self) -> str:
        """Short reason: ``strerror`` for an OS error, the parser message for bad JSON."""
        if isinstance(self.cause, json.JSONDecodeError):
            return self.cause.msg
        if isinstance(self.cause, OSError) and self.cause.strerror:
            return self.cause.strerror
        return str(self.cause)


def read_json(path: str | Path) -> object:
    """Parse the UTF-8 JSON file at ``path``; raise ``JsonReadError`` on any failure."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise JsonReadError(JsonReadFailure.MISSING, p, exc) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise JsonReadError(JsonReadFailure.UNREADABLE, p, exc) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonReadError(JsonReadFailure.INVALID, p, exc) from exc
