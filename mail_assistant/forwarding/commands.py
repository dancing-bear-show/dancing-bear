from __future__ import annotations

"""Convenience orchestration helpers for forwarding commands."""

from ..context import MailContext
from .consumers import (
    ForwardingListConsumer,
    ForwardingAddConsumer,
    ForwardingStatusConsumer,
    ForwardingEnableConsumer,
    ForwardingDisableConsumer,
)
from .processors import (
    ForwardingListProcessor,
    ForwardingAddProcessor,
    ForwardingStatusProcessor,
    ForwardingEnableProcessor,
    ForwardingDisableProcessor,
)
from .producers import (
    ForwardingListProducer,
    ForwardingAddProducer,
    ForwardingStatusProducer,
    ForwardingEnableProducer,
    ForwardingDisableProducer,
)


def run_forwarding_list(args) -> int:
    context = MailContext.from_args(args)
    consumer = ForwardingListConsumer(context=context)
    processor = ForwardingListProcessor()
    producer = ForwardingListProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_forwarding_add(args) -> int:
    context = MailContext.from_args(args)
    consumer = ForwardingAddConsumer(context=context, email=args.email)
    processor = ForwardingAddProcessor()
    producer = ForwardingAddProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_forwarding_status(args) -> int:
    context = MailContext.from_args(args)
    consumer = ForwardingStatusConsumer(context=context)
    processor = ForwardingStatusProcessor()
    producer = ForwardingStatusProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 2))


def run_forwarding_enable(args) -> int:
    context = MailContext.from_args(args)
    consumer = ForwardingEnableConsumer(
        context=context,
        email=args.email,
        disposition=getattr(args, "disposition", "leaveInInbox"),
    )
    processor = ForwardingEnableProcessor()
    producer = ForwardingEnableProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 3))


def run_forwarding_disable(args) -> int:
    context = MailContext.from_args(args)
    consumer = ForwardingDisableConsumer(context=context)
    processor = ForwardingDisableProcessor()
    producer = ForwardingDisableProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 3))
