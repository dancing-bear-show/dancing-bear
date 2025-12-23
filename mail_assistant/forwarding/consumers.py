from __future__ import annotations

"""Consumers for forwarding pipelines."""

from dataclasses import dataclass
from typing import Optional

from core.pipeline import Consumer

from ..context import MailContext


@dataclass
class ForwardingListPayload:
    """Payload for forwarding list."""

    context: MailContext


@dataclass
class ForwardingAddPayload:
    """Payload for forwarding add."""

    context: MailContext
    email: str


@dataclass
class ForwardingStatusPayload:
    """Payload for forwarding status."""

    context: MailContext


@dataclass
class ForwardingEnablePayload:
    """Payload for forwarding enable."""

    context: MailContext
    email: str
    disposition: str


@dataclass
class ForwardingDisablePayload:
    """Payload for forwarding disable."""

    context: MailContext


class ForwardingListConsumer(Consumer[ForwardingListPayload]):
    """Consume args to create list payload."""

    def __init__(self, context: MailContext):
        self._context = context

    def consume(self) -> ForwardingListPayload:
        return ForwardingListPayload(context=self._context)


class ForwardingAddConsumer(Consumer[ForwardingAddPayload]):
    """Consume args to create add payload."""

    def __init__(self, context: MailContext, email: str):
        self._context = context
        self._email = email

    def consume(self) -> ForwardingAddPayload:
        return ForwardingAddPayload(context=self._context, email=self._email)


class ForwardingStatusConsumer(Consumer[ForwardingStatusPayload]):
    """Consume args to create status payload."""

    def __init__(self, context: MailContext):
        self._context = context

    def consume(self) -> ForwardingStatusPayload:
        return ForwardingStatusPayload(context=self._context)


class ForwardingEnableConsumer(Consumer[ForwardingEnablePayload]):
    """Consume args to create enable payload."""

    def __init__(self, context: MailContext, email: str, disposition: str):
        self._context = context
        self._email = email
        self._disposition = disposition

    def consume(self) -> ForwardingEnablePayload:
        return ForwardingEnablePayload(
            context=self._context,
            email=self._email,
            disposition=self._disposition,
        )


class ForwardingDisableConsumer(Consumer[ForwardingDisablePayload]):
    """Consume args to create disable payload."""

    def __init__(self, context: MailContext):
        self._context = context

    def consume(self) -> ForwardingDisablePayload:
        return ForwardingDisablePayload(context=self._context)
