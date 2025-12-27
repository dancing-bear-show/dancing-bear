"""Mail-specific test fixtures.

Gmail client fakes, YAML helpers, and output capture utilities.
"""

from __future__ import annotations

import io
import os
import tempfile
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Dict, List, Optional


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
