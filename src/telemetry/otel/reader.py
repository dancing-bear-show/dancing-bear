"""Read OTLP telemetry data from JSONL files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.fileutil import find_rotated_files, iter_rotated_jsonl
from telemetry.otel.models import (
    OTLPEventsRecord,
    OTLPMetricsRecord,
    OTLPSpansRecord,
)


class _FromDict(Protocol):
    """Structural type for classes with a from_dict class method."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Any: ...

# Filenames
METRICS_FILE = "metrics.jsonl"
EVENTS_FILE = "events.jsonl"
SPANS_FILE = "spans.jsonl"


@dataclass(frozen=True)
class OTLPDataDir:
    """Represents the directory containing OTLP telemetry data files."""

    path: Path

    @classmethod
    def default(cls) -> OTLPDataDir:
        """Get the default data directory (~/.config/otel/)."""
        return cls(path=Path.home() / ".config" / "otel")

    @classmethod
    def from_env(cls) -> OTLPDataDir:
        """Get data directory from TELEMETRY_DATA_DIR env var, or default."""
        data_dir = os.getenv("TELEMETRY_DATA_DIR")
        if data_dir:
            return cls(path=Path(data_dir))
        return cls.default()


class OTLPReader:
    """Reads OTLP telemetry data from JSONL files."""

    def __init__(self, data_dir: OTLPDataDir | None = None) -> None:
        """Initialize reader.

        Args:
            data_dir: OTLPDataDir to read from. If None, uses from_env().
        """
        self.data_dir = data_dir or OTLPDataDir.from_env()

    def read_metrics(self) -> list[OTLPMetricsRecord]:
        """Read all metrics from metrics.jsonl (and rotation files)."""
        return self._read_jsonl(self.data_dir.path / METRICS_FILE, OTLPMetricsRecord)

    def read_events(self) -> list[OTLPEventsRecord]:
        """Read all events from events.jsonl (and rotation files)."""
        return self._read_jsonl(self.data_dir.path / EVENTS_FILE, OTLPEventsRecord)

    def read_spans(self) -> list[OTLPSpansRecord]:
        """Read all spans from spans.jsonl (and rotation files)."""
        return self._read_jsonl(self.data_dir.path / SPANS_FILE, OTLPSpansRecord)

    def _read_jsonl(self, file_path: Path, record_class: type[_FromDict]) -> list:
        """Read *file_path* plus rotation files, parsing into *record_class*; skip malformed lines."""
        records = []
        for data in iter_rotated_jsonl(file_path, tolerant=True):
            try:
                records.append(record_class.from_dict(data))
            except (KeyError, ValueError):
                continue
        return records

    def _find_all_files(self, filename: str) -> list[Path]:
        """Return main JSONL plus numbered/timestamped rotation files for *filename*."""
        return find_rotated_files(self.data_dir.path / filename)

    def data_dir_size(self) -> int:
        """Get total size of all JSONL files (including rotated) in bytes."""
        total = 0
        for filename in (METRICS_FILE, EVENTS_FILE, SPANS_FILE):
            for fpath in self._find_all_files(filename):
                total += fpath.stat().st_size
        return total

    def file_sizes(self) -> dict[str, int]:
        """Get per-file sizes in bytes (including rotated backups).

        Returns:
            Dict mapping filename to total size in bytes.
        """
        sizes = {}
        for filename in (METRICS_FILE, EVENTS_FILE, SPANS_FILE):
            total = sum(
                fpath.stat().st_size
                for fpath in self._find_all_files(filename)
            )
            sizes[filename] = total
        return sizes
