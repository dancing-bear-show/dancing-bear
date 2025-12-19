from __future__ import annotations

"""Convenience orchestration helpers for filters commands."""

from ..context import MailContext
from .consumers import (
    FiltersPlanConsumer,
    FiltersSyncConsumer,
    FiltersImpactConsumer,
    FiltersExportConsumer,
    FiltersSweepConsumer,
    FiltersSweepRangeConsumer,
    FiltersPruneConsumer,
    FiltersAddForwardConsumer,
    FiltersAddTokenConsumer,
    FiltersRemoveTokenConsumer,
)
from .processors import (
    FiltersPlanProcessor,
    FiltersSyncProcessor,
    FiltersImpactProcessor,
    FiltersExportProcessor,
    FiltersSweepProcessor,
    FiltersSweepRangeProcessor,
    FiltersPruneProcessor,
    FiltersAddForwardProcessor,
    FiltersAddTokenProcessor,
    FiltersRemoveTokenProcessor,
)
from .producers import (
    FiltersPlanProducer,
    FiltersSyncProducer,
    FiltersImpactProducer,
    FiltersExportProducer,
    FiltersSweepProducer,
    FiltersSweepRangeProducer,
    FiltersPruneProducer,
    FiltersAddForwardProducer,
    FiltersAddTokenProducer,
    FiltersRemoveTokenProducer,
)


def run_filters_plan(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersPlanConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersPlanProcessor()
    producer = FiltersPlanProducer()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_filters_sync(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersSyncConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersSyncProcessor()
    envelope = processor.process(payload)
    if not envelope.ok():
        diagnostics = envelope.diagnostics or {}
        message = diagnostics.get("message", "Filters sync failed.")
        print(message)
        return diagnostics.get("code", 1)

    producer = FiltersSyncProducer(
        context.get_gmail_client(),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    producer.produce(envelope)
    return 0


def run_filters_impact(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersImpactConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersImpactProcessor()
    producer = FiltersImpactProducer()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_filters_export(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersExportConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersExportProcessor()
    producer = FiltersExportProducer()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_filters_sweep(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersSweepConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersSweepProcessor()
    producer = FiltersSweepProducer(
        payload.client,
        pages=payload.pages,
        batch_size=payload.batch_size,
        max_msgs=payload.max_msgs,
        dry_run=payload.dry_run,
    )
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_filters_sweep_range(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersSweepRangeConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersSweepRangeProcessor()
    producer = FiltersSweepRangeProducer(
        payload.client,
        pages=payload.pages,
        batch_size=payload.batch_size,
        max_msgs=payload.max_msgs,
        dry_run=payload.dry_run,
    )
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_filters_prune_empty(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersPruneConsumer(context)
    payload = consumer.consume()
    processor = FiltersPruneProcessor()
    producer = FiltersPruneProducer(
        payload.client,
        dry_run=payload.dry_run,
    )
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_filters_add_forward_by_label(args) -> int:
    context = MailContext.from_args(args)
    consumer = FiltersAddForwardConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = FiltersAddForwardProcessor()
    envelope = processor.process(payload)
    if not envelope.ok():
        diagnostics = envelope.diagnostics or {}
        message = diagnostics.get("message", "Filters add-forward failed.")
        print(message)
        return diagnostics.get("code", 1)

    producer = FiltersAddForwardProducer(
        payload.client,
        dry_run=payload.dry_run,
    )
    producer.produce(envelope)
    return 0


def run_filters_add_from_token(args) -> int:
    context = MailContext.from_args(args)
    try:
        payload = FiltersAddTokenConsumer(context).consume()
    except ValueError as exc:
        print(exc)
        return 1
    processor = FiltersAddTokenProcessor()
    envelope = processor.process(payload)
    producer = FiltersAddTokenProducer(payload.client, dry_run=payload.dry_run)
    producer.produce(envelope)
    return 0


def run_filters_rm_from_token(args) -> int:
    context = MailContext.from_args(args)
    try:
        payload = FiltersRemoveTokenConsumer(context).consume()
    except ValueError as exc:
        print(exc)
        return 1
    processor = FiltersRemoveTokenProcessor()
    envelope = processor.process(payload)
    producer = FiltersRemoveTokenProducer(payload.client, dry_run=payload.dry_run)
    producer.produce(envelope)
    return 0
