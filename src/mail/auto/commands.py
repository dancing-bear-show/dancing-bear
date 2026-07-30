"""Convenience orchestration helpers for auto commands."""
from __future__ import annotations

from pathlib import Path

from ..context import MailContext
from .consumers import (
    AutoProposeConsumer,
    AutoSummaryConsumer,
    AutoApplyConsumer,
)
from .processors import (
    AutoProposeProcessor,
    AutoSummaryProcessor,
    AutoApplyProcessor,
)
from .producers import (
    AutoProposeProducer,
    AutoSummaryProducer,
    AutoApplyProducer,
)


def run_auto_propose(args) -> int:
    context = MailContext.from_args(args)
    consumer = AutoProposeConsumer(
        context=context,
        out_path=Path(args.out),
        days=int(args.days),
        pages=int(args.pages),
        protect=getattr(args, "protect", []) or [],
        dry_run=getattr(args, "dry_run", False),
        log_path=getattr(args, "log", "logs/auto_runs.jsonl"),
    )
    processor = AutoProposeProcessor()
    producer = AutoProposeProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_auto_summary(args) -> int:
    consumer = AutoSummaryConsumer(proposal_path=Path(args.proposal))
    processor = AutoSummaryProcessor()
    producer = AutoSummaryProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_auto_apply(args) -> int:
    context = MailContext.from_args(args)
    consumer = AutoApplyConsumer(
        context=context,
        proposal_path=Path(args.proposal),
        cutoff_days=getattr(args, "cutoff_days", None),
        batch_size=getattr(args, "batch_size", 500),
        dry_run=getattr(args, "dry_run", False),
        log_path=getattr(args, "log", "logs/auto_runs.jsonl"),
    )
    processor = AutoApplyProcessor()
    producer = AutoApplyProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))
