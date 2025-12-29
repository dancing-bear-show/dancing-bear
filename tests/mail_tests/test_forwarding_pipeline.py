"""Tests for mail/forwarding pipeline (consumers, processors, producers)."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Dict, List, Optional, Any

from mail.context import MailContext
from mail.forwarding.consumers import (
    ForwardingListConsumer,
    ForwardingAddConsumer,
    ForwardingStatusConsumer,
    ForwardingEnableConsumer,
    ForwardingDisableConsumer,
)
from mail.forwarding.processors import (
    ForwardingListProcessor,
    ForwardingAddProcessor,
    ForwardingStatusProcessor,
    ForwardingEnableProcessor,
    ForwardingDisableProcessor,
)
from mail.forwarding.producers import (
    ForwardingListProducer,
    ForwardingAddProducer,
    ForwardingStatusProducer,
    ForwardingEnableProducer,
    ForwardingDisableProducer,
)


@dataclass
class FakeForwardingClient:
    """Fake Gmail client with forwarding methods for testing."""

    forwarding_addresses: List[Dict[str, Any]] = field(default_factory=list)
    verified_addresses: set = field(default_factory=set)
    auto_forwarding: Dict[str, Any] = field(default_factory=dict)

    # Track mutations
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


def _make_context_with_client(client: FakeForwardingClient) -> MailContext:
    """Create a MailContext with a fake client injected."""
    args = SimpleNamespace(credentials=None, token=None, profile=None)
    ctx = MailContext.from_args(args)
    ctx.gmail_client = client
    return ctx


class ForwardingListPipelineTests(unittest.TestCase):
    """Tests for forwarding list pipeline."""

    def test_list_returns_addresses(self):
        client = FakeForwardingClient(
            forwarding_addresses=[
                {"forwardingEmail": "a@example.com", "verificationStatus": "accepted"},
                {"forwardingEmail": "b@example.com", "verificationStatus": "pending"},
            ]
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingListConsumer(context=ctx)
        payload = consumer.consume()

        processor = ForwardingListProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(len(envelope.payload.addresses), 2)

    def test_list_producer_outputs_addresses(self):
        client = FakeForwardingClient(
            forwarding_addresses=[
                {"forwardingEmail": "test@example.com", "verificationStatus": "accepted"},
            ]
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingListConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingListProcessor()
        envelope = processor.process(payload)
        producer = ForwardingListProducer()

        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)

        output = buf.getvalue()
        self.assertIn("test@example.com", output)

    def test_list_handles_empty(self):
        client = FakeForwardingClient(forwarding_addresses=[])
        ctx = _make_context_with_client(client)

        consumer = ForwardingListConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingListProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(len(envelope.payload.addresses), 0)


class ForwardingAddPipelineTests(unittest.TestCase):
    """Tests for forwarding add pipeline."""

    def test_add_creates_address(self):
        client = FakeForwardingClient()
        ctx = _make_context_with_client(client)

        consumer = ForwardingAddConsumer(context=ctx, email="new@example.com")
        payload = consumer.consume()

        processor = ForwardingAddProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.email, "new@example.com")
        self.assertEqual(envelope.payload.status, "pending")
        self.assertIn("new@example.com", client.created_addresses)

    def test_add_producer_outputs_status(self):
        client = FakeForwardingClient()
        ctx = _make_context_with_client(client)

        consumer = ForwardingAddConsumer(context=ctx, email="add@example.com")
        payload = consumer.consume()
        processor = ForwardingAddProcessor()
        envelope = processor.process(payload)
        producer = ForwardingAddProducer()

        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)

        output = buf.getvalue()
        self.assertIn("add@example.com", output)


class ForwardingStatusPipelineTests(unittest.TestCase):
    """Tests for forwarding status pipeline."""

    def test_status_returns_enabled(self):
        client = FakeForwardingClient(
            auto_forwarding={
                "enabled": True,
                "emailAddress": "forward@example.com",
                "disposition": "leaveInInbox",
            }
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingStatusConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingStatusProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertTrue(envelope.payload.enabled)
        self.assertEqual(envelope.payload.email_address, "forward@example.com")
        self.assertEqual(envelope.payload.disposition, "leaveInInbox")

    def test_status_returns_disabled(self):
        client = FakeForwardingClient(
            auto_forwarding={"enabled": False}
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingStatusConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingStatusProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertFalse(envelope.payload.enabled)

    def test_status_producer_outputs_info(self):
        client = FakeForwardingClient(
            auto_forwarding={
                "enabled": True,
                "emailAddress": "dest@example.com",
                "disposition": "archive",
            }
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingStatusConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingStatusProcessor()
        envelope = processor.process(payload)
        producer = ForwardingStatusProducer()

        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)

        output = buf.getvalue()
        self.assertIn("dest@example.com", output)


class ForwardingEnablePipelineTests(unittest.TestCase):
    """Tests for forwarding enable pipeline."""

    def test_enable_sets_forwarding(self):
        client = FakeForwardingClient(
            verified_addresses={"verified@example.com"}
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingEnableConsumer(
            context=ctx,
            email="verified@example.com",
            disposition="leaveInInbox",
        )
        payload = consumer.consume()
        processor = ForwardingEnableProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload.email_address, "verified@example.com")
        self.assertEqual(envelope.payload.disposition, "leaveInInbox")
        self.assertTrue(client.forwarding_settings[-1]["enabled"])

    def test_enable_fails_for_unverified_address(self):
        client = FakeForwardingClient(
            verified_addresses={"other@example.com"}
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingEnableConsumer(
            context=ctx,
            email="unverified@example.com",
            disposition="leaveInInbox",
        )
        payload = consumer.consume()
        processor = ForwardingEnableProcessor()
        envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.diagnostics.get("code"), 2)
        self.assertIn("not verified", envelope.diagnostics.get("error", ""))

    def test_enable_producer_outputs_success(self):
        client = FakeForwardingClient(
            verified_addresses={"good@example.com"}
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingEnableConsumer(
            context=ctx,
            email="good@example.com",
            disposition="archive",
        )
        payload = consumer.consume()
        processor = ForwardingEnableProcessor()
        envelope = processor.process(payload)
        producer = ForwardingEnableProducer()

        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)

        output = buf.getvalue()
        self.assertIn("good@example.com", output)


class ForwardingDisablePipelineTests(unittest.TestCase):
    """Tests for forwarding disable pipeline."""

    def test_disable_turns_off_forwarding(self):
        client = FakeForwardingClient(
            auto_forwarding={"enabled": True, "emailAddress": "old@example.com"}
        )
        ctx = _make_context_with_client(client)

        consumer = ForwardingDisableConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingDisableProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        self.assertTrue(envelope.payload.success)
        self.assertFalse(client.forwarding_settings[-1]["enabled"])

    def test_disable_producer_outputs_success(self):
        client = FakeForwardingClient()
        ctx = _make_context_with_client(client)

        consumer = ForwardingDisableConsumer(context=ctx)
        payload = consumer.consume()
        processor = ForwardingDisableProcessor()
        envelope = processor.process(payload)
        producer = ForwardingDisableProducer()

        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)

        output = buf.getvalue()
        self.assertIn("disabled", output.lower())


if __name__ == "__main__":
    unittest.main()
