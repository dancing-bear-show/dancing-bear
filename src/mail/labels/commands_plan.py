"""Plan/sync/export pipeline commands for labels."""
from __future__ import annotations

from ..context import MailContext
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


def _analyze_labels(labels: list) -> dict:
    """Analyze labels for the doctor command."""
    from collections import Counter
    names = [lbl.get("name", "") for lbl in labels if isinstance(lbl, dict)]
    counts = Counter(names)
    dups = [n for n, c in counts.items() if c > 1]
    parts = [n.split('/') for n in names]
    max_depth = max((len(ps) for ps in parts), default=0)
    top_counts = Counter(ps[0] for ps in parts if ps)
    vis_l = Counter((lbl.get('labelListVisibility') or 'unset') for lbl in labels if isinstance(lbl, dict))
    vis_m = Counter((lbl.get('messageListVisibility') or 'unset') for lbl in labels if isinstance(lbl, dict))
    imapish = [n for n in names if n.startswith('[Gmail]') or n.lower().startswith('imap/')]
    unset_vis = [lbl.get('name') for lbl in labels if not lbl.get('labelListVisibility') or not lbl.get('messageListVisibility')]
    return {
        'total': len(names),
        'duplicates': dups,
        'max_depth': max_depth,
        'top_counts': dict(top_counts.most_common(10)),
        'vis_label': dict(vis_l),
        'vis_message': dict(vis_m),
        'imapish': imapish,
        'unset_visibility': unset_vis,
    }


def _run_labels_pipeline(consumer, processor, producer) -> int:
    """Run a consumer → processor → producer pipeline; return 0 on success."""
    try:
        payload = consumer.consume()
    except ValueError as exc:
        print(exc)
        return 1
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else 1


def run_labels_plan(args) -> int:
    context = MailContext.from_args(args)
    return _run_labels_pipeline(
        LabelsPlanConsumer(context),
        LabelsPlanProcessor(),
        LabelsPlanProducer(),
    )


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
    LabelsSyncProducer(
        context.get_gmail_client(),
        dry_run=bool(getattr(args, "dry_run", False)),
    ).produce(envelope)
    return 0 if envelope.ok() else 1


def run_labels_export(args) -> int:
    context = MailContext.from_args(args)
    return _run_labels_pipeline(
        LabelsExportConsumer(context),
        LabelsExportProcessor(),
        LabelsExportProducer(),
    )


def run_labels_list(args) -> int:
    """List all labels."""
    from ..utils.cli_helpers import gmail_client_authenticated
    client = getattr(args, "_gmail_client", None) or gmail_client_authenticated(args)
    labels = client.list_labels()
    for lab in labels:
        name = lab.get("name", "<unknown>")
        lab_id = lab.get("id", "")
        print(f"{lab_id}\t{name}")
    return 0
