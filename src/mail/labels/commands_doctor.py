"""Doctor/health commands for labels."""
from __future__ import annotations

import argparse
import time
from collections import Counter, defaultdict


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


# (field name, default value) pairs for visibility fields that must be set.
_VISIBILITY_DEFAULTS = (
    ('labelListVisibility', 'labelShow'),
    ('messageListVisibility', 'show'),
)


def _missing_visibility_fields(lbl: dict) -> dict:
    """Return the subset of visibility defaults missing from a label."""
    return {field: default for field, default in _VISIBILITY_DEFAULTS if not lbl.get(field)}


def _fix_label_visibility(client, labels: list) -> int:
    """Set default visibility on labels missing it. Returns count of changes."""
    changed = 0
    for lbl in labels:
        if lbl.get('type') == 'system':
            continue
        missing = _missing_visibility_fields(lbl)
        if not missing:
            continue
        body = {"name": lbl.get('name'), **missing}
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
    from .commands_plan import _analyze_labels

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


def _prune_one_label(client, lab: dict, dry_run: bool, sleep_s: float) -> bool:
    """Delete (or preview deleting) a single empty label. Returns True if deleted."""
    name = lab.get("name")
    if dry_run:
        print(f"Would delete label: {name}")
        return False
    if not _delete_label_with_retry(client, lab.get("id", ""), name or ""):
        return False
    if sleep_s > 0:
        time.sleep(sleep_s)
    return True


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

    deleted = sum(
        1 for lab in empty_labels if _prune_one_label(client, lab, dry_run, sleep_s)
    )

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


def _pattern_matches(email: str, domain: str, pattern: str) -> bool:
    """Return True if email/domain matches a single protected pattern."""
    if pattern.startswith('@'):
        return email.endswith(pattern) or domain == pattern.lstrip('@')
    return pattern == email


def _is_protected_sender(email: str, protected_patterns: list) -> bool:
    """Check if sender matches any protected pattern."""
    domain = _extract_domain(email)
    return any(
        _pattern_matches(email, domain, p)
        for p in protected_patterns
        if p
    )


def _classify_domain(hints: dict, count: int) -> str | None:
    """Classify domain based on message hints. Returns label or None."""
    threshold = max(1, count // 3)
    if hints['promotions'] >= threshold:
        return 'Lists/Commercial'
    if hints['list'] >= threshold:
        return 'Lists/Newsletters'
    return None


def _domain_for_message(hdrs: dict, protected: list) -> str | None:
    """Return the sender domain for a message's headers, or None if protected/unresolvable."""
    email = _extract_email_from_header(hdrs.get('from', ''))
    if _is_protected_sender(email, protected):
        return None
    dom = _extract_domain(email)
    return dom or None


def _record_domain_hints(hints: dict, hdrs: dict, msg: dict) -> None:
    """Increment list/promotions hint counters in-place from message headers/labels."""
    if 'list-unsubscribe' in hdrs or 'list-id' in hdrs:
        hints['list'] += 1
    if 'CATEGORY_PROMOTIONS' in set(msg.get('labelIds') or []):
        hints['promotions'] += 1


def _collect_domain_stats(client, msgs: list, protected: list) -> tuple[Counter, dict]:
    """Collect domain counts and hints from messages."""
    domain_counts: Counter = Counter()
    domain_hints: dict = defaultdict(lambda: {"list": 0, "promotions": 0})

    for m in msgs:
        hdrs = client.headers_to_dict(m)
        dom = _domain_for_message(hdrs, protected)
        if not dom:
            continue
        domain_counts[dom] += 1
        _record_domain_hints(domain_hints[dom], hdrs, m)

    return domain_counts, domain_hints


def run_labels_learn(args) -> int:
    """Learn label suggestions from message patterns."""
    from pathlib import Path
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


def _apply_one_suggestion(client, s: dict, dry_run: bool) -> bool:
    """Apply a single label suggestion. Returns True if a filter was created/planned."""
    from ..utils.filters import action_to_label_changes

    dom = s.get('domain')
    label = s.get('label')
    if not dom or not label:
        return False
    crit = {'query': f'from:({dom})'}
    add_ids, _ = action_to_label_changes(client, {'add': [label]})
    act = {'addLabelIds': add_ids}
    if dry_run:
        print(f"Would create: from:({dom}) -> add=[{label}]")
    else:
        client.create_filter(crit, act)
        print(f"Created rule: from:({dom}) -> add=[{label}]")
    return True


def _maybe_sweep_after_suggestions(args, dry_run: bool) -> None:
    """Run the follow-up filters sweep if --sweep-days was requested."""
    if not getattr(args, 'sweep_days', None):
        return
    from ..filters.commands import run_filters_sweep

    args2 = argparse.Namespace(
        credentials=args.credentials, token=args.token, cache=args.cache,
        config=args.config, days=int(args.sweep_days), only_inbox=False,
        pages=args.pages, batch_size=args.batch_size, max_msgs=None, dry_run=dry_run,
        profile=getattr(args, "profile", None),
    )
    print(f"\nSweeping back {args.sweep_days} days for suggestions …")
    run_filters_sweep(args2)


def _apply_suggestions(args, sugg: list, dry_run: bool) -> int:
    """Authenticate and apply a non-empty list of suggestions. Returns count applied."""
    from ..config_resolver import resolve_paths_profile
    from ..gmail_api import GmailClient

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

    created = sum(1 for s in sugg if _apply_one_suggestion(client, s, dry_run))
    _maybe_sweep_after_suggestions(args, dry_run)
    return created


def run_labels_apply_suggestions(args) -> int:
    """Apply learned label suggestions."""
    from ..yamlio import load_config

    doc = load_config(args.config)
    sugg = doc.get('suggestions') or []
    dry_run = getattr(args, 'dry_run', False)

    created = _apply_suggestions(args, sugg, dry_run) if sugg else 0

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


def _sweep_one_parent(client, name_to_id: dict, parent: str, args, dry_run: bool) -> int:
    """Sweep child-labeled messages under one parent. Returns messages touched."""
    from ..utils.batch import apply_in_chunks

    parent_id = name_to_id.get(parent) or client.ensure_label(parent)
    child_ids = [lid for name, lid in name_to_id.items() if name.startswith(parent + "/")]
    if not child_ids:
        print(f"No child labels under {parent}/; skipping")
        return 0

    ids = client.list_message_ids(label_ids=child_ids, max_pages=int(args.pages), page_size=int(args.batch_size))
    if dry_run:
        print(f"[{parent}] Would add to {len(ids)} messages")
        return len(ids)

    apply_in_chunks(
        lambda chunk, _pid=parent_id: client.batch_modify_messages(chunk, add_label_ids=[_pid]),
        ids,
        int(args.batch_size),
    )
    print(f"[{parent}] Added to {len(ids)} messages")
    return len(ids)


def run_labels_sweep_parents(args) -> int:
    """Add parent labels to messages that have child labels."""
    from ..utils.cli_helpers import gmail_provider_from_args

    client = gmail_provider_from_args(args)
    client.authenticate()
    name_to_id = client.get_label_id_map()
    parents = [n.strip() for n in (args.names or "").split(",") if n.strip()]
    dry_run = getattr(args, 'dry_run', False)

    total_added = sum(
        _sweep_one_parent(client, name_to_id, parent, args, dry_run) for parent in parents
    )
    print(f"Sweep-parents complete. Messages touched: {total_added}")
    return 0
