from __future__ import annotations

"""Labels command orchestration helpers."""

from ..context import MailContext
from ..utils.plan import print_plan_summary
from .consumers import (
    LabelsPlanConsumer,
    LabelsSyncConsumer,
    LabelsExportConsumer,
)
from .processors import (
    LabelsPlanProcessor,
    LabelsSyncProcessor,
    LabelsExportProcessor,
)
from .producers import (
    LabelsPlanProducer,
    LabelsSyncProducer,
    LabelsExportProducer,
)


def run_labels_plan(args) -> int:
    context = MailContext.from_args(args)
    consumer = LabelsPlanConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = LabelsPlanProcessor()
    producer = LabelsPlanProducer()

    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_labels_sync(args) -> int:
    context = MailContext.from_args(args)
    consumer = LabelsSyncConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = LabelsSyncProcessor()
    envelope = processor.process(payload)
    producer = LabelsSyncProducer(
        context.get_gmail_client(),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_labels_export(args) -> int:
    context = MailContext.from_args(args)
    consumer = LabelsExportConsumer(context)
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1

    processor = LabelsExportProcessor()
    envelope = processor.process(payload)
    producer = LabelsExportProducer()
    producer.produce(envelope)
    return 0 if envelope.ok() else 1
