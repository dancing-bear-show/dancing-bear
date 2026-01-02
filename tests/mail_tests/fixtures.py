"""Mail-specific test fixtures.

Gmail client fakes and CLI arg helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

# Re-export shared fixtures for backwards compatibility
from tests.fixtures import capture_stdout, temp_yaml_file, write_yaml

# Re-export FakeGmailClient from centralized fakes module
from tests.fakes.gmail import FakeGmailClient, make_gmail_client

__all__ = [
    "capture_stdout",
    "temp_yaml_file",
    "write_yaml",
    "make_args",
    "FakeGmailClient",
    "make_gmail_client",
    "FakeMailContext",
    "FakeForwardingClient",
    # Label/message factories
    "make_user_label",
    "make_system_label",
    "make_label_with_visibility",
    "make_message",
    "make_message_with_headers",
    # Mock builders
    "make_success_envelope",
    "make_error_envelope",
    "make_mock_mail_context",
    # Test data constants
    "NESTED_LABELS",
    "IMAP_STYLE_LABELS",
    # CLI register test helpers
    "noop_handler",
    "make_noop_handlers",
    "CLIRegisterTestCase",
]


# -----------------------------------------------------------------------------
# Test data constants
# -----------------------------------------------------------------------------

NESTED_LABELS = [
    {"name": "A"},
    {"name": "A/B"},
    {"name": "A/B/C"},
    {"name": "A/B/C/D"},
]

IMAP_STYLE_LABELS = [
    {"name": "[Gmail]/Trash"},
    {"name": "IMAP/Folder"},
    {"name": "Normal"},
]


# -----------------------------------------------------------------------------
# CLI arg helpers
# -----------------------------------------------------------------------------


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
# Fake mail context and clients
# -----------------------------------------------------------------------------


class FakeMailContext:
    """Fake MailContext for testing pipelines.

    Example:
        client = FakeGmailClient()
        context = FakeMailContext(gmail_client=client)
    """

    def __init__(self, gmail_client: Optional[Any] = None):
        self._gmail_client = gmail_client

    def get_gmail_client(self):
        """Return the configured Gmail client or raise RuntimeError."""
        if self._gmail_client is None:
            raise RuntimeError("No Gmail client configured")
        return self._gmail_client


@dataclass
class FakeForwardingClient:
    """Fake Gmail client with forwarding methods for testing.

    Example:
        client = FakeForwardingClient(
            verified_addresses={"user@example.com"},
            auto_forwarding={"enabled": True, "emailAddress": "fwd@example.com"}
        )
    """

    forwarding_addresses: List[Dict[str, Any]] = field(default_factory=list)
    verified_addresses: set = field(default_factory=set)
    auto_forwarding: Dict[str, Any] = field(default_factory=dict)
    created_addresses: List[str] = field(default_factory=list)
    forwarding_settings: List[Dict] = field(default_factory=list)

    def authenticate(self) -> None:
        """No-op for fake client."""

    def list_forwarding_addresses_info(self) -> List[Dict[str, Any]]:
        return list(self.forwarding_addresses)

    def list_forwarding_addresses(self) -> List[Dict]:
        return [{"forwardingEmail": addr, "verificationStatus": "accepted"}
                for addr in self.verified_addresses]

    def get_verified_forwarding_addresses(self) -> set:
        return set(self.verified_addresses)

    def create_forwarding_address(self, email: str) -> Dict[str, Any]:
        self.created_addresses.append(email)
        return {"forwardingEmail": email, "verificationStatus": "pending"}

    def get_auto_forwarding(self) -> Dict[str, Any]:
        return dict(self.auto_forwarding)

    def set_auto_forwarding(
        self,
        enabled: bool,
        email: Optional[str] = None,
        disposition: Optional[str] = None,
    ) -> Dict[str, Any]:
        settings = {"enabled": enabled}
        if email:
            settings["emailAddress"] = email
        if disposition:
            settings["disposition"] = disposition
        self.forwarding_settings.append(settings)
        self.auto_forwarding = settings
        return settings


# -----------------------------------------------------------------------------
# Label and message factories
# -----------------------------------------------------------------------------


def make_user_label(
    name: str,
    label_id: Optional[str] = None,
    messages: int = 0,
    **kwargs,
) -> Dict[str, any]:
    """Create a user label dict for testing.

    Args:
        name: Label name (e.g., "Work", "Work/Projects")
        label_id: Optional label ID (defaults to "LBL_{name}")
        messages: Message count (messagesTotal)
        **kwargs: Additional label properties (color, visibility, etc.)

    Example:
        make_user_label("Work", "L1", messages=10)
        make_user_label("Reports", color={"textColor": "#000"})
    """
    return {
        "id": label_id or f"LBL_{name}",
        "name": name,
        "type": "user",
        "messagesTotal": messages,
        **kwargs,
    }


def make_system_label(name: str, messages: int = 0) -> Dict[str, any]:
    """Create a system label dict for testing.

    Args:
        name: System label name (e.g., "INBOX", "SENT", "TRASH")
        messages: Message count

    Example:
        make_system_label("INBOX")
    """
    return {"id": name, "name": name, "type": "system", "messagesTotal": messages}


def make_label_with_visibility(
    name: str,
    label_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, any]:
    """Create a user label with default visibility settings.

    Args:
        name: Label name
        label_id: Optional label ID
        **kwargs: Additional properties

    Example:
        make_label_with_visibility("Reports", "LBL_REPORTS")
    """
    return {
        **make_user_label(name, label_id, **kwargs),
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }


def make_message(
    msg_id: str,
    label_ids: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, any]:
    """Create a message dict for testing.

    Args:
        msg_id: Message ID
        label_ids: List of label IDs on the message
        **kwargs: Additional message properties

    Example:
        make_message("m1", ["INBOX", "CATEGORY_PROMOTIONS"])
    """
    return {"id": msg_id, "labelIds": label_ids or [], **kwargs}


def make_message_with_headers(
    msg_id: str,
    headers: Dict[str, str],
    label_ids: Optional[List[str]] = None,
    internal_date: Optional[int] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Create a Gmail message dict with headers for testing.

    Args:
        msg_id: Message ID
        headers: Dict of header name -> value (e.g., {"From": "a@b.com"})
        label_ids: List of label IDs on the message
        internal_date: Optional internal date timestamp
        **kwargs: Additional message properties

    Example:
        make_message_with_headers("m1", {"From": "user@example.com", "Subject": "Hi"})
    """
    hdrs = [{"name": k, "value": v} for k, v in headers.items()]
    msg = {
        "id": msg_id,
        "threadId": f"thread_{msg_id}",
        "labelIds": label_ids or ["INBOX"],
        "payload": {"headers": hdrs},
        **kwargs,
    }
    if internal_date is not None:
        msg["internalDate"] = str(internal_date)
    return msg


# -----------------------------------------------------------------------------
# Mock builders
# -----------------------------------------------------------------------------


def make_success_envelope(payload: Any = None, **kwargs) -> MagicMock:
    """Create a mock success ResultEnvelope.

    Args:
        payload: Optional payload for the envelope
        **kwargs: Additional attributes to set on the mock

    Example:
        envelope = make_success_envelope(payload={"labels": []})
        mock_processor.return_value.process.return_value = envelope
    """
    from core.pipeline import ResultEnvelope

    envelope = MagicMock(spec=ResultEnvelope)
    envelope.ok.return_value = True
    envelope.status = "success"
    envelope.payload = payload
    envelope.diagnostics = {}
    for k, v in kwargs.items():
        setattr(envelope, k, v)
    return envelope


def make_error_envelope(diagnostics: Optional[Dict[str, Any]] = None, **kwargs) -> MagicMock:
    """Create a mock error ResultEnvelope.

    Args:
        diagnostics: Optional diagnostics dict (e.g., {"error": "msg", "code": 1})
        **kwargs: Additional attributes to set on the mock

    Example:
        envelope = make_error_envelope(diagnostics={"code": 5})
        mock_processor.return_value.process.return_value = envelope
    """
    from core.pipeline import ResultEnvelope

    envelope = MagicMock(spec=ResultEnvelope)
    envelope.ok.return_value = False
    envelope.status = "error"
    envelope.payload = None
    envelope.diagnostics = diagnostics or {}
    for k, v in kwargs.items():
        setattr(envelope, k, v)
    return envelope


def make_mock_mail_context(
    gmail_client: Any = None,
    outlook_client: Any = None,
) -> MagicMock:
    """Create a mock MailContext with given clients.

    Args:
        gmail_client: Optional Gmail client to return from get_gmail_client()
        outlook_client: Optional Outlook client to return from get_outlook_client()

    Example:
        client = FakeGmailClient()
        mock_ctx = make_mock_mail_context(gmail_client=client)
        mock_ctx_cls.from_args.return_value = mock_ctx
    """
    mock_ctx = MagicMock()
    if gmail_client is not None:
        mock_ctx.gmail_client = gmail_client
        mock_ctx.get_gmail_client.return_value = gmail_client
    if outlook_client is not None:
        mock_ctx.outlook_client = outlook_client
        mock_ctx.get_outlook_client.return_value = outlook_client
    return mock_ctx


# -----------------------------------------------------------------------------
# CLI register test helpers
# -----------------------------------------------------------------------------


def noop_handler(*_args, **_kwargs):
    """No-op handler for CLI registration tests."""
    pass


def make_noop_handlers(*names: str) -> Dict[str, callable]:
    """Create a dict of noop handlers for CLI registration.

    Args:
        *names: Handler names (e.g., "f_list", "f_export")

    Returns:
        Dict mapping names to noop_handler

    Example:
        handlers = make_noop_handlers("f_list", "f_export", "f_sync")
        register(subparsers, **handlers)
    """
    return {name: noop_handler for name in names}


class CLIRegisterTestCase:
    """Mixin for CLI register tests. Provides parser setup.

    Subclasses should set `parser` in setUp by calling their
    parser factory function.

    Example:
        class TestFiltersSync(CLIRegisterTestCase, unittest.TestCase):
            def setUp(self):
                self.parser = make_filters_parser()

            def test_sync_subcommand(self):
                args = self.parse("filters", "sync", "--config", "/c.yaml")
                self.assertEqual(args.filters_cmd, "sync")
    """

    parser = None  # Set in setUp

    def parse(self, *argv: str):
        """Parse command-line arguments. Shorthand for self.parser.parse_args()."""
        return self.parser.parse_args(list(argv))
