"""Convenience orchestration helpers for filters commands."""
from __future__ import annotations

from typing import Any, Callable, Optional, Type

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


def _run_filter_pipeline(
    args,
    consumer_cls: Type,
    processor_cls: Type,
    producer_factory: Callable[[Any], Any],
    handle_error: Optional[Callable[[Any], int]] = None,
) -> int:
    """Generic pipeline runner for filter commands.

    Args:
        args: CLI arguments
        consumer_cls: Consumer class to instantiate
        processor_cls: Processor class to instantiate
        producer_factory: Callable that takes payload and returns producer instance
        handle_error: Optional custom error handler for envelope errors

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    context = MailContext.from_args(args)
    consumer = consumer_cls(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = processor_cls()
    envelope = processor.process(payload)

    if not envelope.ok():
        if handle_error:
            return handle_error(envelope)
        diagnostics = envelope.diagnostics or {}
        message = diagnostics.get("message", "Pipeline failed.")
        print(message)
        return diagnostics.get("code", 1)

    producer = producer_factory(payload)
    producer.produce(envelope)
    return 0


def run_filters_plan(args) -> int:
    return _run_filter_pipeline(
        args,
        FiltersPlanConsumer,
        FiltersPlanProcessor,
        lambda _: FiltersPlanProducer(),
    )


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
    return _run_filter_pipeline(
        args,
        FiltersImpactConsumer,
        FiltersImpactProcessor,
        lambda _: FiltersImpactProducer(),
    )


def run_filters_export(args) -> int:
    return _run_filter_pipeline(
        args,
        FiltersExportConsumer,
        FiltersExportProcessor,
        lambda _: FiltersExportProducer(),
    )


def run_filters_sweep(args) -> int:
    return _run_filter_pipeline(
        args,
        FiltersSweepConsumer,
        FiltersSweepProcessor,
        lambda p: FiltersSweepProducer(
            p.client,
            pages=p.pages,
            batch_size=p.batch_size,
            max_msgs=p.max_msgs,
            dry_run=p.dry_run,
        ),
    )


def run_filters_sweep_range(args) -> int:
    return _run_filter_pipeline(
        args,
        FiltersSweepRangeConsumer,
        FiltersSweepRangeProcessor,
        lambda p: FiltersSweepRangeProducer(
            p.client,
            pages=p.pages,
            batch_size=p.batch_size,
            max_msgs=p.max_msgs,
            dry_run=p.dry_run,
        ),
    )


def run_filters_prune_empty(args) -> int:
    return _run_filter_pipeline(
        args,
        FiltersPruneConsumer,
        FiltersPruneProcessor,
        lambda p: FiltersPruneProducer(
            p.client,
            dry_run=p.dry_run,
        ),
    )


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
    return _run_filter_pipeline(
        args,
        FiltersAddTokenConsumer,
        FiltersAddTokenProcessor,
        lambda p: FiltersAddTokenProducer(p.client, dry_run=p.dry_run),
    )


def run_filters_rm_from_token(args) -> int:
    return _run_filter_pipeline(
        args,
        FiltersRemoveTokenConsumer,
        FiltersRemoveTokenProcessor,
        lambda p: FiltersRemoveTokenProducer(p.client, dry_run=p.dry_run),
    )


def run_filters_list(args) -> int:
    """List all filters."""
    from ..utils.cli_helpers import gmail_client_authenticated

    client = getattr(args, "_gmail_client", None) or gmail_client_authenticated(args)
    # Map label IDs to names for friendly output
    id_to_name = {lab.get("id", ""): lab.get("name", "") for lab in client.list_labels()}

    def ids_to_names(ids):
        return [id_to_name.get(x, x) for x in ids or []]

    for f in client.list_filters():
        fid = f.get("id", "")
        c = f.get("criteria", {})
        a = f.get("action", {})
        forward = a.get("forward")
        add = ids_to_names(a.get("addLabelIds"))
        rem = ids_to_names(a.get("removeLabelIds"))
        print(f"{fid}\tfrom={c.get('from','')} subject={c.get('subject','')} query={c.get('query','')} | add={add} rem={rem} fwd={forward}")
    return 0


def run_filters_delete(args) -> int:
    """Delete a filter by ID."""
    from ..utils.cli_helpers import gmail_provider_from_args

    client = gmail_provider_from_args(args)
    client.authenticate()
    fid = args.id
    client.delete_filter(fid)
    print(f"Deleted filter id={fid}")
    return 0
