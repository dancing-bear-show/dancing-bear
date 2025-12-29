"""Mail-specific test fixtures.

Gmail client fakes and CLI arg helpers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, List, Optional

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
    # Label/message factories
    "make_user_label",
    "make_system_label",
    "make_label_with_visibility",
    "make_message",
    # CLI register test helpers
    "noop_handler",
    "make_noop_handlers",
    "CLIRegisterTestCase",
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


# -----------------------------------------------------------------------------
# CLI register test helpers
# -----------------------------------------------------------------------------


def noop_handler(*args, **kwargs):
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
