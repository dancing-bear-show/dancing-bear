"""Telemetry data retention policy and pruning logic."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from telemetry.timeutil import now_utc
from telemetry.otel.config import RetentionConfig
from telemetry.otel.models import (
    OTLPEventsRecord,
    OTLPMetricsRecord,
    OTLPSpansRecord,
)
from telemetry.otel.reader import OTLPReader


@dataclass
class PruneResult:
    """Result of a prune operation."""

    data_type: str  # "metrics" | "events" | "spans"
    records_before: int
    records_after: int
    records_removed: int
    bytes_before: int
    bytes_after: int
    bytes_removed: int
    dry_run: bool


class TelemetryPruner:
    """Prunes old telemetry data based on retention policy."""

    def __init__(self, reader: OTLPReader, config: RetentionConfig) -> None:
        """Initialize pruner.

        Args:
            reader: OTLPReader to read telemetry data.
            config: RetentionConfig with keep_days for each data type.
        """
        self.reader = reader
        self.config = config

    def prune(self, data_type: str, dry_run: bool = True) -> PruneResult:
        """Prune old records of a single data type.

        Args:
            data_type: "metrics", "events", or "spans".
            dry_run: If True, don't modify files — just report what would be deleted.

        Returns:
            PruneResult with before/after stats.

        Raises:
            ValueError: If data_type is invalid or safety net triggered.
        """
        if data_type not in ("metrics", "events", "spans"):
            raise ValueError(f"Invalid data_type: {data_type}")

        file_path, retention_days = self._get_file_config(data_type)

        if not file_path.exists():
            return PruneResult(
                data_type=data_type,
                records_before=0,
                records_after=0,
                records_removed=0,
                bytes_before=0,
                bytes_after=0,
                bytes_removed=0,
                dry_run=dry_run,
            )

        bytes_before = file_path.stat().st_size
        cutoff = now_utc() - timedelta(days=retention_days)

        kept_records, records_before, records_after = self._filter_records(
            file_path, data_type, cutoff
        )

        records_removed = records_before - records_after
        if records_removed > 0 and records_after < self.config.min_records_after_prune:
            raise ValueError(
                f"Pruning would leave only {records_after} records "
                f"(minimum: {self.config.min_records_after_prune}). Aborted."
            )

        if not dry_run:
            self._write_records(file_path, kept_records)

        bytes_after = file_path.stat().st_size if not dry_run else (
            sum(len(json.dumps(r)) + 1 for r in kept_records)
        )

        return PruneResult(
            data_type=data_type,
            records_before=records_before,
            records_after=records_after,
            records_removed=records_removed,
            bytes_before=bytes_before,
            bytes_after=bytes_after,
            bytes_removed=bytes_before - bytes_after,
            dry_run=dry_run,
        )

    def _get_file_config(self, data_type: str) -> tuple[Path, int]:
        """Get file path and retention days for a data type."""
        base_path = self.reader.data_dir.path
        type_config: dict[str, tuple[Path, int]] = {
            "metrics": (base_path / "metrics.jsonl", self.config.metrics.keep_days),
            "events": (base_path / "events.jsonl", self.config.events.keep_days),
            "spans": (base_path / "spans.jsonl", self.config.spans.keep_days),
        }
        return type_config[data_type]

    def _parse_and_filter_line(
        self, line: str, data_type: str, cutoff: datetime
    ) -> dict | None:
        """Parse one JSONL line and return its record dict if it should be kept.

        Returns None when the line is unparseable or the record predates *cutoff*.
        """
        try:
            record_dict = json.loads(line)
            ts = self._get_earliest_timestamp(data_type, record_dict)
            if ts is None or ts >= cutoff:
                return record_dict
        except (KeyError, ValueError):
            pass
        return None

    def _apply_line(
        self, line: str, data_type: str, cutoff: datetime, kept_records: list
    ) -> bool:
        """Parse+filter one non-blank line, appending to kept_records if kept.

        Returns True when the line was a record (blank lines are not counted).
        """
        if not line.strip():
            return False
        result = self._parse_and_filter_line(line, data_type, cutoff)
        if result is not None:
            kept_records.append(result)
        return True

    def _filter_records(
        self, file_path: Path, data_type: str, cutoff: datetime
    ) -> tuple[list, int, int]:
        """Filter records older than cutoff timestamp."""
        kept_records: list = []
        records_before = 0

        try:
            with open(file_path) as f:
                for line in f:
                    if self._apply_line(line, data_type, cutoff, kept_records):
                        records_before += 1
        except OSError as e:
            raise OSError(f"Failed to read {file_path}: {e}") from e

        return kept_records, records_before, len(kept_records)

    def _get_earliest_timestamp(self, data_type: str, record_dict: dict) -> datetime | None:
        """Get earliest timestamp from a record dict."""
        try:
            if data_type == "metrics":
                record = OTLPMetricsRecord.from_dict(record_dict)
                return record.earliest_timestamp()
            elif data_type == "events":
                record = OTLPEventsRecord.from_dict(record_dict)
                return min((e.timestamp for e in record.log_records), default=None)
            else:  # spans
                record = OTLPSpansRecord.from_dict(record_dict)
                return min((s.start_timestamp for s in record.spans), default=None)
        except (KeyError, ValueError):
            return None

    def _write_records(self, file_path: Path, records: list) -> None:
        """Write records back to file."""
        try:
            with open(file_path, "w") as f:
                for record in records:
                    f.write(json.dumps(record) + "\n")
        except OSError as e:
            raise OSError(f"Failed to write {file_path}: {e}") from e

    def prune_all(self, dry_run: bool = True) -> list[PruneResult]:
        """Prune all data types.

        Args:
            dry_run: If True, don't modify files.

        Returns:
            List of PruneResult for each data type.
        """
        return [self.prune(dt, dry_run=dry_run) for dt in ("metrics", "events", "spans")]
