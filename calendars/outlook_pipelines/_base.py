"""Shared imports and constants for Outlook calendar pipelines."""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.pipeline import Processor, ResultEnvelope

from calendars.yamlio import load_config as _load_yaml
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
ERR_OUTLOOK_SERVICE_REQUIRED = "Outlook service is required"
ERR_CONFIG_MUST_CONTAIN_EVENTS = "Config must contain events: [] list"
MSG_PREVIEW_COMPLETE = "Preview complete."


def load_events_config(
    config_path: Path,
    loader=None,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[ResultEnvelope]]:
    """Load config and extract events list, returning error envelope if invalid.

    Returns (events, None) on success, or (None, error_envelope) on failure.
    """
    load_fn = loader if loader is not None else _load_yaml
    try:
        cfg = load_fn(str(config_path))
    except Exception as exc:
        return None, ResultEnvelope(
            status="error",
            diagnostics={"message": f"Failed to read config: {exc}", "code": 2},
        )
    items = cfg.get("events") if isinstance(cfg, dict) else None
    if not isinstance(items, list):
        return None, ResultEnvelope(
            status="error",
            diagnostics={"message": ERR_CONFIG_MUST_CONTAIN_EVENTS, "code": 2},
        )
    return items, None


__all__ = [
    # Re-exports
    "_dt",
    "re",
    "defaultdict",
    "dataclass",
    "Path",
    "Any",
    "Dict",
    "List",
    "Optional",
    "Sequence",
    "Tuple",
    "Processor",
    "ResultEnvelope",
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
    "ERR_OUTLOOK_SERVICE_REQUIRED",
    "ERR_CONFIG_MUST_CONTAIN_EVENTS",
    "MSG_PREVIEW_COMPLETE",
    # Helpers
    "load_events_config",
]
