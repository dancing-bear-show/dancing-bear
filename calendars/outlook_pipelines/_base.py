"""Shared imports and constants for Outlook calendar pipelines."""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.pipeline import ResultEnvelope, SafeProcessor

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
) -> List[Dict[str, Any]]:
    """Load config and extract events list, raising on invalid config."""
    load_fn = loader if loader is not None else _load_yaml
    cfg = load_fn(str(config_path))
    items = cfg.get("events") if isinstance(cfg, dict) else None
    if not isinstance(items, list):
        raise ValueError(ERR_CONFIG_MUST_CONTAIN_EVENTS)
    return items


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
    "ERR_OUTLOOK_SERVICE_REQUIRED",
    "ERR_CONFIG_MUST_CONTAIN_EVENTS",
    "MSG_PREVIEW_COMPLETE",
    "ERR_CODE_CONFIG",
    "ERR_CODE_CALENDAR",
    "ERR_CODE_API",
    "LOG_DRY_RUN",
    "DEFAULT_IMPORT_CALENDAR",
    # Helpers
    "load_events_config",
]
