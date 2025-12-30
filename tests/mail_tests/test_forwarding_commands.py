"""Tests for mail/forwarding/commands.py orchestration helpers."""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from mail.forwarding.commands import (
    run_forwarding_list,
    run_forwarding_add,
    run_forwarding_status,
    run_forwarding_enable,
    run_forwarding_disable,
)


@dataclass
class FakeForwardingClient:
    """Fake Gmail client with forwarding methods for testing."""

    forwarding_addresses: List[Dict[str, Any]] = field(default_factory=list)
    verified_addresses: set = field(default_factory=set)
    auto_forwarding: Dict[str, Any] = field(default_factory=dict)
    created_addresses: List[str] = field(default_factory=list)
    forwarding_settings: List[Dict] = field(default_factory=list)

    def authenticate(self) -> None:
        pass

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


def _make_args(**kwargs):
    """Create args namespace with defaults."""
    defaults = {
        "credentials": None,
        "token": None,
        "profile": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_mock_context(client):
    """Create a mock MailContext with the given client."""
    mock_ctx = MagicMock()
    mock_ctx.gmail_client = client
    mock_ctx.get_gmail_client.return_value = client
    return mock_ctx


class TestRunForwardingList(unittest.TestCase):
    """Tests for run_forwarding_list command."""

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls):
        client = FakeForwardingClient(
            forwarding_addresses=[
                {"forwardingEmail": "test@example.com", "verificationStatus": "accepted"}
            ]
        )
        mock_ctx_cls.from_args.return_value = _make_mock_context(client)

        args = _make_args()
        result = run_forwarding_list(args)

        self.assertEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_with_empty_list(self, mock_ctx_cls):
        client = FakeForwardingClient(forwarding_addresses=[])
        mock_ctx_cls.from_args.return_value = _make_mock_context(client)

        args = _make_args()
        result = run_forwarding_list(args)

        self.assertEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingListProcessor")
    def test_returns_error_code_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 5}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args()
        result = run_forwarding_list(args)

        self.assertEqual(result, 5)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingListProcessor")
    def test_returns_default_code_when_no_code_in_diagnostics(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args()
        result = run_forwarding_list(args)

        self.assertEqual(result, 1)


class TestRunForwardingAdd(unittest.TestCase):
    """Tests for run_forwarding_add command."""

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls):
        client = FakeForwardingClient()
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args(email="new@example.com")
        result = run_forwarding_add(args)

        self.assertEqual(result, 0)
        self.assertIn("new@example.com", client.created_addresses)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingAddProcessor")
    def test_returns_error_code_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 7}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args(email="bad@example.com")
        result = run_forwarding_add(args)

        self.assertEqual(result, 7)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingAddProcessor")
    def test_returns_default_code_when_no_diagnostics(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = None

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args(email="fail@example.com")
        result = run_forwarding_add(args)

        self.assertEqual(result, 1)


class TestRunForwardingStatus(unittest.TestCase):
    """Tests for run_forwarding_status command."""

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_when_enabled(self, mock_ctx_cls):
        client = FakeForwardingClient(
            auto_forwarding={
                "enabled": True,
                "emailAddress": "fwd@example.com",
                "disposition": "archive",
            }
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args()
        result = run_forwarding_status(args)

        self.assertEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_when_disabled(self, mock_ctx_cls):
        client = FakeForwardingClient(
            auto_forwarding={"enabled": False}
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args()
        result = run_forwarding_status(args)

        self.assertEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingStatusProcessor")
    def test_returns_error_code_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 9}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args()
        result = run_forwarding_status(args)

        self.assertEqual(result, 9)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingStatusProcessor")
    def test_returns_default_code_2_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args()
        result = run_forwarding_status(args)

        self.assertEqual(result, 2)


class TestRunForwardingEnable(unittest.TestCase):
    """Tests for run_forwarding_enable command."""

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls):
        client = FakeForwardingClient(
            verified_addresses={"verified@example.com"}
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args(email="verified@example.com", disposition="leaveInInbox")
        result = run_forwarding_enable(args)

        self.assertEqual(result, 0)
        self.assertTrue(client.forwarding_settings[-1]["enabled"])

    @patch("mail.forwarding.commands.MailContext")
    def test_uses_default_disposition(self, mock_ctx_cls):
        client = FakeForwardingClient(
            verified_addresses={"verified@example.com"}
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        # Args without disposition attribute
        args = SimpleNamespace(
            credentials=None,
            token=None,
            profile=None,
            email="verified@example.com",
        )
        result = run_forwarding_enable(args)

        self.assertEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_nonzero_for_unverified_address(self, mock_ctx_cls):
        client = FakeForwardingClient(
            verified_addresses={"other@example.com"}
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args(email="unverified@example.com", disposition="leaveInInbox")
        result = run_forwarding_enable(args)

        self.assertNotEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingEnableProcessor")
    def test_returns_error_code_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 11}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args(email="test@example.com", disposition="archive")
        result = run_forwarding_enable(args)

        self.assertEqual(result, 11)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingEnableProcessor")
    def test_returns_default_code_3_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args(email="test@example.com", disposition="archive")
        result = run_forwarding_enable(args)

        self.assertEqual(result, 3)


class TestRunForwardingDisable(unittest.TestCase):
    """Tests for run_forwarding_disable command."""

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_on_success(self, mock_ctx_cls):
        client = FakeForwardingClient(
            auto_forwarding={"enabled": True, "emailAddress": "old@example.com"}
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args()
        result = run_forwarding_disable(args)

        self.assertEqual(result, 0)
        self.assertFalse(client.forwarding_settings[-1]["enabled"])

    @patch("mail.forwarding.commands.MailContext")
    def test_returns_zero_when_already_disabled(self, mock_ctx_cls):
        client = FakeForwardingClient(
            auto_forwarding={"enabled": False}
        )
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        args = _make_args()
        result = run_forwarding_disable(args)

        self.assertEqual(result, 0)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingDisableProcessor")
    def test_returns_error_code_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {"code": 13}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args()
        result = run_forwarding_disable(args)

        self.assertEqual(result, 13)

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingDisableProcessor")
    def test_returns_default_code_3_on_failure(self, mock_proc_cls, mock_ctx_cls):
        mock_ctx = MagicMock()
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_envelope = MagicMock()
        mock_envelope.ok.return_value = False
        mock_envelope.diagnostics = {}

        mock_proc = MagicMock()
        mock_proc.process.return_value = mock_envelope
        mock_proc_cls.return_value = mock_proc

        args = _make_args()
        result = run_forwarding_disable(args)

        self.assertEqual(result, 3)


class TestCommandIntegration(unittest.TestCase):
    """Integration tests verifying full pipeline wiring."""

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingListProducer")
    def test_list_calls_producer_produce(self, mock_prod_cls, mock_ctx_cls):
        client = FakeForwardingClient(forwarding_addresses=[])
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        args = _make_args()
        run_forwarding_list(args)

        mock_producer.produce.assert_called_once()

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingAddProducer")
    def test_add_calls_producer_produce(self, mock_prod_cls, mock_ctx_cls):
        client = FakeForwardingClient()
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        args = _make_args(email="test@example.com")
        run_forwarding_add(args)

        mock_producer.produce.assert_called_once()

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingStatusProducer")
    def test_status_calls_producer_produce(self, mock_prod_cls, mock_ctx_cls):
        client = FakeForwardingClient(auto_forwarding={"enabled": False})
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        args = _make_args()
        run_forwarding_status(args)

        mock_producer.produce.assert_called_once()

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingEnableProducer")
    def test_enable_calls_producer_produce(self, mock_prod_cls, mock_ctx_cls):
        client = FakeForwardingClient(verified_addresses={"test@example.com"})
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        args = _make_args(email="test@example.com", disposition="archive")
        run_forwarding_enable(args)

        mock_producer.produce.assert_called_once()

    @patch("mail.forwarding.commands.MailContext")
    @patch("mail.forwarding.commands.ForwardingDisableProducer")
    def test_disable_calls_producer_produce(self, mock_prod_cls, mock_ctx_cls):
        client = FakeForwardingClient()
        mock_ctx = MagicMock()
        mock_ctx.gmail_client = client
        mock_ctx_cls.from_args.return_value = mock_ctx

        mock_producer = MagicMock()
        mock_prod_cls.return_value = mock_producer

        args = _make_args()
        run_forwarding_disable(args)

        mock_producer.produce.assert_called_once()


if __name__ == "__main__":
    unittest.main()
