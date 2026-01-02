"""Labels command orchestration helpers."""
from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

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


def _print_doctor_report(info: dict) -> None:
    """Print label analysis report."""
    print(f"Total labels: {info['total']}")
    dups_suffix = (' ; ' + ','.join(info['duplicates'])) if info['duplicates'] else ''
    print(f"Duplicates: {len(info['duplicates'])}{dups_suffix}")
    print(f"Max depth: {info['max_depth']}")
    print(f"Top-level groups: {info['top_counts']}")
    print(f"Visibility labelListVisibility: {info['vis_label']}")
    print(f"Visibility messageListVisibility: {info['vis_message']}")
    imap_suffix = (' ; ' + ','.join(info['imapish'])) if info['imapish'] else ''
    print(f"IMAP-style labels: {len(info['imapish'])}{imap_suffix}")
    print(f"Unset visibility count: {len(info['unset_visibility'])}")


def _fix_label_visibility(client, labels: list) -> int:
    """Set default visibility on labels missing it. Returns count of changes."""
    changed = 0
    for lbl in labels:
        if lbl.get('type') == 'system':
            continue
        body = {"name": lbl.get('name')}
        need_update = False
        if not lbl.get('labelListVisibility'):
            body['labelListVisibility'] = 'labelShow'
            need_update = True
        if not lbl.get('messageListVisibility'):
            body['messageListVisibility'] = 'show'
            need_update = True
        if need_update:
            client.update_label(lbl.get('id', ''), body)
            print(f"Updated visibility: {lbl.get('name')}")
            changed += 1
    return changed


def _redirect_imap_labels(client, redirect_specs: list) -> int:
    """Redirect messages from old labels to new labels. Returns count of changes."""
    from ..utils.batch import apply_in_chunks

    map_pairs = [(old.strip(), new.strip()) for spec in redirect_specs
                 if '=' in spec for old, new in [spec.split('=', 1)]]
    if not map_pairs:
        return 0

    changed = 0
    name_to_id = client.get_label_id_map()
    for old, new in map_pairs:
        old_id = name_to_id.get(old)
        new_id = name_to_id.get(new) or client.ensure_label(new)
        if not old_id or not new_id:
            print(f"Skip redirect: {old}->{new} (missing label)")
            continue
        ids = client.list_message_ids(label_ids=[old_id], max_pages=50, page_size=500)
        apply_in_chunks(
            lambda chunk, nid=new_id, oid=old_id: client.batch_modify_messages(
                chunk, add_label_ids=[nid], remove_label_ids=[oid]
            ),
            ids,
            500,
        )
        print(f"Redirected {len(ids)} messages {old} -> {new}")
        changed += 1
    return changed


def _delete_imap_labels(client, label_names: list) -> int:
    """Delete labels by name. Returns count of deletions."""
    changed = 0
    name_to_id = client.get_label_id_map()
    for name in label_names:
        lid = name_to_id.get(name)
        if lid:
            client.delete_label(lid)
            print(f"Deleted label: {name}")
            changed += 1
    return changed


def run_labels_doctor(args) -> int:
    """Diagnose and optionally fix label issues."""
    from ..utils.cli_helpers import gmail_provider_from_args

    client = gmail_provider_from_args(args)
    client.authenticate()
    labs = client.list_labels(use_cache=getattr(args, 'use_cache', False), ttl=getattr(args, 'cache_ttl', 300))
    _print_doctor_report(_analyze_labels(labs))

    changed = 0
    if getattr(args, 'set_visibility', False):
        changed += _fix_label_visibility(client, labs)
    if getattr(args, 'imap_redirect', None):
        changed += _redirect_imap_labels(client, args.imap_redirect)
    if getattr(args, 'imap_delete', None):
        changed += _delete_imap_labels(client, args.imap_delete)

    if changed:
        print(f"Applied {changed} change(s).")
    return 0


def _delete_label_with_retry(client, label_id: str, name: str, max_retries: int = 3) -> bool:
    """Delete a label with exponential backoff retry."""
    last_err = None
    for attempt in range(max_retries):
        try:
            client.delete_label(label_id)
            print(f"Deleted label: {name}")
            return True
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (2 ** attempt))
    print(f"Warning: failed to delete label {name}: {last_err}")
    return False


def _get_empty_user_labels(labels: list) -> list:
    """Filter to user labels with zero messages."""
    return [lab for lab in labels
            if lab.get("type") == "user" and int(lab.get("messagesTotal", 0)) == 0]


def run_labels_prune_empty(args) -> int:
    """Delete labels with zero messages."""
    from ..utils.cli_helpers import gmail_provider_from_args

    client = gmail_provider_from_args(args)
    client.authenticate()

    empty_labels = _get_empty_user_labels(client.list_labels())
    limit = int(getattr(args, 'limit', 0) or 0)
    sleep_s = float(getattr(args, 'sleep_sec', 0.0) or 0.0)
    dry_run = getattr(args, 'dry_run', False)

    if limit:
        empty_labels = empty_labels[:limit]

    deleted = 0
    for lab in empty_labels:
        name = lab.get("name")
        if dry_run:
            print(f"Would delete label: {name}")
        elif _delete_label_with_retry(client, lab.get("id", ""), name or ""):
            deleted += 1
            if sleep_s > 0:
                time.sleep(sleep_s)

    print(f"Prune complete. Deleted: {deleted}")
    return 0


def _extract_email_from_header(from_val: str) -> str:
    """Extract email address from 'Name <email>' format."""
    f = (from_val or '').lower()
    if '<' in f and '>' in f:
        try:
            f = f.split('<')[-1].split('>')[0]
        except Exception:  # nosec B110 - malformed From header
            pass
    return f.strip()


def _extract_domain(email: str) -> str:
    """Extract domain from email address."""
    return email.split('@')[-1].lower().strip() if '@' in email else email.lower().strip()


def _is_protected_sender(email: str, protected_patterns: list) -> bool:
    """Check if sender matches any protected pattern."""
    domain = _extract_domain(email)
    for pattern in protected_patterns:
        if not pattern:
            continue
        if pattern.startswith('@'):
            if email.endswith(pattern) or domain == pattern.lstrip('@'):
                return True
        elif pattern == email:
            return True
    return False


def _classify_domain(hints: dict, count: int) -> str | None:
    """Classify domain based on message hints. Returns label or None."""
    threshold = max(1, count // 3)
    if hints['promotions'] >= threshold:
        return 'Lists/Commercial'
    if hints['list'] >= threshold:
        return 'Lists/Newsletters'
    return None


def _collect_domain_stats(client, msgs: list, protected: list) -> tuple[Counter, dict]:
    """Collect domain counts and hints from messages."""
    domain_counts: Counter = Counter()
    domain_hints: dict = defaultdict(lambda: {"list": 0, "promotions": 0})

    for m in msgs:
        hdrs = client.headers_to_dict(m)
        frm = hdrs.get('from', '')
        email = _extract_email_from_header(frm)
        if _is_protected_sender(email, protected):
            continue
        dom = _extract_domain(email)
        if not dom:
            continue
        domain_counts[dom] += 1
        if 'list-unsubscribe' in hdrs or 'list-id' in hdrs:
            domain_hints[dom]['list'] += 1
        if 'CATEGORY_PROMOTIONS' in set(m.get('labelIds') or []):
            domain_hints[dom]['promotions'] += 1

    return domain_counts, domain_hints


def run_labels_learn(args) -> int:
    """Learn label suggestions from message patterns."""
    from ..config_resolver import resolve_paths_profile
    from ..gmail_api import GmailClient
    from ..utils.filters import build_gmail_query

    creds_path, tok_path = resolve_paths_profile(
        arg_credentials=args.credentials,
        arg_token=args.token,
        profile=getattr(args, "profile", None),
    )
    client = GmailClient(
        credentials_path=creds_path,
        token_path=tok_path,
        cache_dir=args.cache,
    )
    client.authenticate()
    q = build_gmail_query({}, days=args.days, only_inbox=args.only_inbox)
    ids = client.list_message_ids(query=q, max_pages=100)
    msgs = client.get_messages_metadata(ids, use_cache=True)

    protected = [p.strip().lower() for p in (args.protect or []) if p and isinstance(p, str)]
    domain_counts, domain_hints = _collect_domain_stats(client, msgs, protected)

    suggestions = []
    for dom, cnt in domain_counts.items():
        if cnt < int(args.min_count):
            continue
        label = _classify_domain(domain_hints[dom], cnt)
        if label:
            suggestions.append({
                'domain': dom,
                'label': label,
                'count': cnt,
                'hints': domain_hints[dom],
            })

    import yaml
    out_doc = {'suggestions': suggestions, 'params': {'days': int(args.days), 'min_count': int(args.min_count)}}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(out_doc, sort_keys=False), encoding='utf-8')
    print(f"Wrote {len(suggestions)} suggestions to {out}")
    return 0


def run_labels_apply_suggestions(args) -> int:
    """Apply learned label suggestions."""
    from ..yamlio import load_config
    from ..config_resolver import resolve_paths_profile
    from ..gmail_api import GmailClient
    from ..utils.filters import action_to_label_changes

    doc = load_config(args.config)
    sugg = doc.get('suggestions') or []
    if not sugg:
        print('No suggestions found.')
        return 0

    creds_path, tok_path = resolve_paths_profile(
        arg_credentials=args.credentials,
        arg_token=args.token,
        profile=getattr(args, "profile", None),
    )
    client = GmailClient(
        credentials_path=creds_path,
        token_path=tok_path,
        cache_dir=args.cache,
    )
    client.authenticate()

    created = 0
    dry_run = getattr(args, 'dry_run', False)
    for s in sugg:
        dom = s.get('domain')
        label = s.get('label')
        if not dom or not label:
            continue
        crit = {'query': f'from:({dom})'}
        add_ids, _ = action_to_label_changes(client, {'add': [label]})
        act = {'addLabelIds': add_ids}
        if dry_run:
            print(f"Would create: from:({dom}) -> add=[{label}]")
        else:
            client.create_filter(crit, act)
            print(f"Created rule: from:({dom}) -> add=[{label}]")
        created += 1

    if getattr(args, 'sweep_days', None):
        from ..filters.commands import run_filters_sweep
        args2 = argparse.Namespace(
            credentials=args.credentials, token=args.token, cache=args.cache,
            config=args.config, days=int(args.sweep_days), only_inbox=False,
            pages=args.pages, batch_size=args.batch_size, max_msgs=None, dry_run=dry_run,
            profile=getattr(args, "profile", None),
        )
        print(f"\nSweeping back {args.sweep_days} days for suggestions …")
        run_filters_sweep(args2)

    print(f"Suggestions applied: {created}")
    return 0


def run_labels_delete(args) -> int:
    """Delete a label by name."""
    from ..utils.cli_helpers import gmail_provider_from_args

    client = gmail_provider_from_args(args)
    client.authenticate()
    name_to_id = client.get_label_id_map()
    name = args.name
    lid = name_to_id.get(name)
    if not lid:
        print(f"Label not found: {name}")
        return 1
    client.delete_label(lid)
    print(f"Deleted label: {name}")
    return 0


def run_labels_sweep_parents(args) -> int:
    """Add parent labels to messages that have child labels."""
    from ..utils.cli_helpers import gmail_provider_from_args
    from ..utils.batch import apply_in_chunks

    client = gmail_provider_from_args(args)
    client.authenticate()
    name_to_id = client.get_label_id_map()
    parents = [n.strip() for n in (args.names or "").split(",") if n.strip()]
    total_added = 0
    dry_run = getattr(args, 'dry_run', False)

    for parent in parents:
        parent_id = name_to_id.get(parent) or client.ensure_label(parent)
        child_ids = [lid for name, lid in name_to_id.items() if name.startswith(parent + "/")]
        if not child_ids:
            print(f"No child labels under {parent}/; skipping")
            continue
        ids = client.list_message_ids(label_ids=child_ids, max_pages=int(args.pages), page_size=int(args.batch_size))
        if dry_run:
            print(f"[{parent}] Would add to {len(ids)} messages")
        else:
            apply_in_chunks(
                lambda chunk: client.batch_modify_messages(chunk, add_label_ids=[parent_id]),
                ids,
                int(args.batch_size),
            )
            print(f"[{parent}] Added to {len(ids)} messages")
        total_added += len(ids)
    print(f"Sweep-parents complete. Messages touched: {total_added}")
    return 0
