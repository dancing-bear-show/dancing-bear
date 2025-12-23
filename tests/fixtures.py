"""Shared test fixtures and utilities.

This module provides common fakes, stubs, and helpers to simplify testing
across the assistant test suite.
"""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import tempfile
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]


# -----------------------------------------------------------------------------
# Path helpers
# -----------------------------------------------------------------------------


def repo_root() -> Path:
    return REPO_ROOT


def repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


def bin_path(name: str) -> Path:
    return REPO_ROOT / "bin" / name


def run(cmd: Sequence[str], cwd: Optional[str] = None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def has_pyyaml() -> bool:
    try:
        return importlib.util.find_spec("yaml") is not None
    except Exception:
        return False


# -----------------------------------------------------------------------------
# YAML config helpers
# -----------------------------------------------------------------------------


def write_yaml(data: dict, dir: Optional[str] = None, filename: str = "config.yaml") -> str:
    """Write a dict to a temporary YAML file, return the path."""
    import yaml

    td = dir or tempfile.mkdtemp()
    p = os.path.join(td, filename)
    with open(p, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)
    return p


@contextmanager
def temp_yaml_file(data: dict, suffix: str = ".yaml"):
    """Context manager that yields a path to a temporary YAML file."""
    import yaml

    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=suffix) as tf:
        yaml.safe_dump(data, tf)
        tf.flush()
        yield tf.name
    os.unlink(tf.name)


# -----------------------------------------------------------------------------
# Output capture helpers
# -----------------------------------------------------------------------------


@contextmanager
def capture_stdout():
    """Context manager that captures stdout and yields a StringIO buffer."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        yield buf


def make_args(**kwargs) -> SimpleNamespace:
    """Create a SimpleNamespace with common CLI arg defaults merged with kwargs."""
    defaults = {
        "credentials": None,
        "token": None,
        "cache": None,
        "profile": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# -----------------------------------------------------------------------------
# Gmail client fakes
# -----------------------------------------------------------------------------


@dataclass
class FakeGmailClient:
    """Configurable fake Gmail client for testing.

    Supports common provider methods: authenticate, list_labels, list_filters,
    list_message_ids, get_messages_metadata, get_message, send_message_raw, etc.

    Example usage:
        client = FakeGmailClient(
            labels=[{"id": "LBL_VIP", "name": "VIP"}],
            filters=[{"id": "F1", "criteria": {"from": "x@y.com"}, "action": {}}],
        )
    """

    labels: List[Dict[str, str]] = field(default_factory=list)
    filters: List[Dict] = field(default_factory=list)
    messages: Dict[str, Dict] = field(default_factory=dict)
    message_ids_by_query: Dict[str, List[str]] = field(default_factory=dict)
    verified_forward_addresses: set = field(default_factory=set)

    # Track mutations
    created_filters: List[Dict] = field(default_factory=list)
    deleted_filter_ids: List[str] = field(default_factory=list)
    modified_batches: List[tuple] = field(default_factory=list)
    sent_messages: List[bytes] = field(default_factory=list)
    created_drafts: List[bytes] = field(default_factory=list)

    def authenticate(self) -> None:
        pass

    def list_labels(self) -> List[Dict[str, str]]:
        return list(self.labels)

    def get_label_id_map(self) -> Dict[str, str]:
        return {lab["name"]: lab["id"] for lab in self.labels}

    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict]:
        return list(self.filters)

    def list_message_ids(
        self, query: Optional[str] = None, label_ids: Optional[List[str]] = None,
        max_pages: int = 1, page_size: int = 500
    ) -> List[str]:
        q = (query or "").lower()
        for pattern, ids in self.message_ids_by_query.items():
            if pattern.lower() in q:
                return ids
        return []

    def get_messages_metadata(self, ids: List[str], use_cache: bool = True) -> List[Dict]:
        return [self.messages.get(mid, {"id": mid}) for mid in ids]

    def get_message(self, msg_id: str, fmt: str = "full") -> Dict:
        return self.messages.get(msg_id, {"id": msg_id, "payload": {"headers": []}})

    def get_message_text(self, msg_id: str) -> str:
        msg = self.messages.get(msg_id, {})
        return msg.get("text", "Message body text.")

    def get_profile(self) -> Dict[str, str]:
        return {"emailAddress": "test@example.com"}

    def create_filter(self, criteria: Dict, action: Dict) -> Dict:
        filt = {"id": f"NEW_{len(self.created_filters)}", "criteria": criteria, "action": action}
        self.created_filters.append(filt)
        return filt

    def delete_filter(self, filter_id: str) -> None:
        self.deleted_filter_ids.append(filter_id)
        self.filters = [f for f in self.filters if f.get("id") != filter_id]

    @property
    def deleted_ids(self) -> List[str]:
        """Alias for deleted_filter_ids for backward compatibility."""
        return self.deleted_filter_ids

    def ensure_label(self, name: str, **kwargs) -> str:
        mapping = self.get_label_id_map()
        if name in mapping:
            return mapping[name]
        new_id = f"LBL_{len(self.labels)}"
        self.labels.append({"id": new_id, "name": name, "type": "user"})
        return new_id

    def create_label(self, **body) -> Dict:
        label = {"id": f"LBL_{len(self.labels)}", "type": "user", **body}
        self.labels.append(label)
        return label

    def update_label(self, label_id: str, body: Dict) -> Dict:
        for lab in self.labels:
            if lab["id"] == label_id:
                lab.update(body)
                return lab
        return {"id": label_id, **body}

    def delete_label(self, label_id: str) -> None:
        self.labels = [lab for lab in self.labels if lab["id"] != label_id]

    def batch_modify_messages(
        self,
        ids: List[str],
        add_label_ids: Optional[List[str]] = None,
        remove_label_ids: Optional[List[str]] = None,
    ) -> None:
        self.modified_batches.append((list(ids), list(add_label_ids or []), list(remove_label_ids or [])))

    def send_message_raw(self, raw_bytes: bytes, thread_id: Optional[str] = None) -> Dict:
        self.sent_messages.append(raw_bytes)
        return {"id": f"SENT_{len(self.sent_messages)}"}

    def create_draft_raw(self, raw_bytes: bytes, thread_id: Optional[str] = None) -> Dict:
        self.created_drafts.append(raw_bytes)
        return {"id": f"DRAFT_{len(self.created_drafts)}"}

    def list_forwarding_addresses(self) -> List[Dict]:
        return [{"forwardingEmail": addr, "verificationStatus": "accepted"}
                for addr in self.verified_forward_addresses]

    def get_verified_forwarding_addresses(self) -> set:
        return set(self.verified_forward_addresses)


def make_gmail_client(
    labels: Optional[List[Dict]] = None,
    filters: Optional[List[Dict]] = None,
    message_ids_by_query: Optional[Dict[str, List[str]]] = None,
) -> FakeGmailClient:
    """Factory for creating a pre-configured FakeGmailClient."""
    return FakeGmailClient(
        labels=labels or [],
        filters=filters or [],
        message_ids_by_query=message_ids_by_query or {},
    )


# -----------------------------------------------------------------------------
# Outlook client fakes
# -----------------------------------------------------------------------------


@dataclass
class FakeOutlookClient:
    """Configurable fake Outlook client for testing.

    Example usage:
        client = FakeOutlookClient(
            events=[{"subject": "Meeting", "start": {...}, "end": {...}}],
            calendars=[{"id": "cal1", "name": "Work"}],
        )
    """

    events: List[Dict] = field(default_factory=list)
    calendars: List[Dict] = field(default_factory=list)
    rules: List[Dict] = field(default_factory=list)
    categories: List[Dict] = field(default_factory=list)

    # Track mutations
    created_events: List[Dict] = field(default_factory=list)
    deleted_event_ids: List[str] = field(default_factory=list)
    updated_events: List[Dict] = field(default_factory=list)

    def authenticate(self) -> None:
        pass

    def list_calendars(self) -> List[Dict]:
        return list(self.calendars)

    def get_calendar_by_name(self, name: str) -> Optional[Dict]:
        for cal in self.calendars:
            if cal.get("name") == name:
                return cal
        return None

    def list_events_in_range(
        self, calendar_id: Optional[str] = None, start: Optional[str] = None,
        end: Optional[str] = None, **kwargs
    ) -> List[Dict]:
        return list(self.events)

    def create_event(self, calendar_id: str, event: Dict) -> Dict:
        event_copy = dict(event)
        event_copy["id"] = f"EVT_{len(self.created_events)}"
        self.created_events.append(event_copy)
        return event_copy

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.deleted_event_ids.append(event_id)

    def update_event(self, calendar_id: str, event_id: str, updates: Dict) -> Dict:
        self.updated_events.append({"id": event_id, **updates})
        return {"id": event_id, **updates}

    def list_rules(self) -> List[Dict]:
        return list(self.rules)

    def list_categories(self) -> List[Dict]:
        return list(self.categories)


def make_outlook_client(
    events: Optional[List[Dict]] = None,
    calendars: Optional[List[Dict]] = None,
) -> FakeOutlookClient:
    """Factory for creating a pre-configured FakeOutlookClient."""
    return FakeOutlookClient(
        events=events or [],
        calendars=calendars or [{"id": "default", "name": "Calendar"}],
    )


# -----------------------------------------------------------------------------
# Pipeline testing helpers (re-exports from core.testing)
# -----------------------------------------------------------------------------

try:
    from core.testing import StubConsumer, StubProcessor, CaptureProducer
except ImportError:
    # Fallback if core.testing not available
    pass


# -----------------------------------------------------------------------------
# Calendar event helpers
# -----------------------------------------------------------------------------


def make_outlook_event(
    subject: str,
    start_iso: str,
    end_iso: str,
    series_id: Optional[str] = None,
    location: Optional[str] = None,
    created: Optional[str] = None,
) -> Dict:
    """Create a fake Outlook event dict for testing."""
    event = {
        "subject": subject,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if series_id:
        event["seriesMasterId"] = series_id
    if location:
        event["location"] = {"displayName": location}
    if created:
        event["createdDateTime"] = created
    return event
