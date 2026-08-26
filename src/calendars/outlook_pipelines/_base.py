"""Shared imports and constants for Outlook calendar pipelines."""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from core.pipeline import ResultEnvelope, SafeProcessor
from core.yamlio import load_config as _load_yaml

from calendars.model import normalize_event
from calendars.selection import compute_window, filter_events_by_day_time

from calendars.location_sync import LocationSync
from calendars.pipeline_base import (
    BaseProducer,
    DateWindowResolver,
    RequestConsumer,
    check_service_required,
    to_iso_str,
)

# Error message constants
ERR_CONFIG_MUST_CONTAIN_EVENTS = "Config must contain events: [] list"
MSG_PREVIEW_COMPLETE = "Preview complete."

# Error codes for diagnostics
ERR_CODE_CONFIG = 2  # Config load/parse errors
ERR_CODE_CALENDAR = 3  # Calendar not found / API errors
ERR_CODE_API = 4  # Graph API / listing errors

# Log prefixes
LOG_DRY_RUN = "[dry-run]"

# Default values
DEFAULT_IMPORT_CALENDAR = "Imported Schedules"


def load_events_config(
    config_path: Path,
    loader=None,
) -> list[dict[str, Any]]:
    """Load config and extract events list, raising on invalid config."""
    load_fn = loader if loader is not None else _load_yaml
    cfg = load_fn(str(config_path))
    items = cfg.get("events") if isinstance(cfg, dict) else None
    if not isinstance(items, list):
        raise ValueError(ERR_CONFIG_MUST_CONTAIN_EVENTS)
    return items


class EventIterationProcessor(SafeProcessor):
    """Template method for processors that iterate normalized config events.

    Shared by remove/verify pipelines, which both load an events config, walk
    each raw dict, normalize it, and delegate per-item handling — differing
    only in what they do with each normalized event and how they seed/return
    their result accumulator. Centralizing the load/iterate/normalize/skip
    boilerplate here keeps each subclass's ``_process_safe`` override to just
    its distinct per-item step.
    """

    def _process_safe(self, payload: Any) -> Any:
        items = self._load_events(payload)
        accumulator = self._init_accumulator(payload)
        for idx, raw in enumerate(items, start=1):
            if not isinstance(raw, dict):
                continue
            nev = normalize_event(raw)
            self._handle_event(payload, idx, nev, accumulator)
        return self._finalize_result(payload, accumulator)

    def _finalize_result(self, payload: Any, accumulator: Any) -> Any:
        """Convert the accumulator into the result, with access to the payload.

        Subclasses that need only the accumulator override ``_finalize``; those
        that also need request fields (a client handle, dry_run, addressing)
        override this instead. Without this seam a payload-needing subclass has
        to copy the whole loop above just to change its last line, which
        re-duplicates the boilerplate this base class exists to centralize.
        """
        return self._finalize(accumulator)

    def _load_events(self, payload: Any) -> list[dict[str, Any]]:
        """Load the events list for this run. Override to rebind the module-local loader symbol a test patches."""
        return load_events_config(payload.config_path, self._config_loader)

    def _init_accumulator(self, payload: Any) -> Any:
        """Override to build the per-run accumulator (logs, counters, plan...)."""
        raise NotImplementedError("Subclass must implement _init_accumulator")

    def _handle_event(self, payload: Any, idx: int, nev: dict[str, Any], accumulator: Any) -> None:
        """Override to process one normalized event, mutating the accumulator."""
        raise NotImplementedError("Subclass must implement _handle_event")

    def _finalize(self, accumulator: Any) -> Any:
        """Override to convert the accumulator into the processor's result type."""
        raise NotImplementedError("Subclass must implement _finalize")


__all__ = [
    # Re-exports
    "_dt",
    "re",
    "defaultdict",
    "dataclass",
    "Path",
    "Any",
    "Sequence",
    "ResultEnvelope",
    "SafeProcessor",

    "_load_yaml",
    "normalize_event",
    "compute_window",
    "filter_events_by_day_time",
    "LocationSync",
    "BaseProducer",
    "DateWindowResolver",
    "RequestConsumer",
    "check_service_required",
    "to_iso_str",
    # Constants
    "ERR_CONFIG_MUST_CONTAIN_EVENTS",
    "MSG_PREVIEW_COMPLETE",
    "ERR_CODE_CONFIG",
    "ERR_CODE_CALENDAR",
    "ERR_CODE_API",
    "LOG_DRY_RUN",
    "DEFAULT_IMPORT_CALENDAR",
    # Helpers
    "load_events_config",
    "EventIterationProcessor",
]
