"""Convenience orchestration helpers for signatures commands."""
from __future__ import annotations

from pathlib import Path

from ..context import MailContext
from .consumers import (
    SignaturesExportConsumer,
    SignaturesSyncConsumer,
    SignaturesNormalizeConsumer,
)
from .processors import (
    SignaturesExportProcessor,
    SignaturesSyncProcessor,
    SignaturesNormalizeProcessor,
)
from .producers import (
    SignaturesExportProducer,
    SignaturesSyncProducer,
    SignaturesNormalizeProducer,
)


def run_signatures_export(args) -> int:
    context = MailContext.from_args(args)
    consumer = SignaturesExportConsumer(
        context=context,
        out_path=Path(args.out),
        assets_dir=Path(args.assets_dir),
    )
    processor = SignaturesExportProcessor()
    producer = SignaturesExportProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_signatures_sync(args) -> int:
    context = MailContext.from_args(args)
    consumer = SignaturesSyncConsumer(
        context=context,
        config_path=args.config,
        dry_run=getattr(args, "dry_run", False),
        send_as=getattr(args, "send_as", None),
        account_display_name=getattr(args, "account_display_name", None),
    )
    processor = SignaturesSyncProcessor()
    producer = SignaturesSyncProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_signatures_normalize(args) -> int:
    consumer = SignaturesNormalizeConsumer(
        config_path=args.config,
        out_html=Path(args.out_html),
        variables=getattr(args, "var", []) or [],
    )
    processor = SignaturesNormalizeProcessor()
    producer = SignaturesNormalizeProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))
