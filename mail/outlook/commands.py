"""Convenience orchestration helpers for Outlook commands."""
from __future__ import annotations

from .auth_commands import (
    run_outlook_auth_device_code,
    run_outlook_auth_poll,
    run_outlook_auth_ensure,
    run_outlook_auth_validate,
)
from .executor import OutlookCommandExecutor
from .helpers import get_outlook_client, resolve_outlook_args
from .consumers import (
    OutlookRulesListConsumer,
    OutlookRulesExportConsumer,
    OutlookRulesSyncConsumer,
    OutlookRulesPlanConsumer,
    OutlookRulesDeleteConsumer,
    OutlookRulesSweepConsumer,
    OutlookCategoriesListConsumer,
    OutlookCategoriesExportConsumer,
    OutlookFoldersSyncConsumer,
    OutlookCalendarAddConsumer,
    OutlookCalendarAddRecurringConsumer,
    OutlookCalendarAddFromConfigConsumer,
)
from .processors import (
    OutlookRulesListProcessor,
    OutlookRulesExportProcessor,
    OutlookRulesSyncProcessor,
    OutlookRulesPlanProcessor,
    OutlookRulesDeleteProcessor,
    OutlookRulesSweepProcessor,
    OutlookCategoriesListProcessor,
    OutlookCategoriesExportProcessor,
    OutlookFoldersSyncProcessor,
    OutlookCalendarAddProcessor,
    OutlookCalendarAddRecurringProcessor,
    OutlookCalendarAddFromConfigProcessor,
)
from .producers import (
    OutlookRulesListProducer,
    OutlookRulesExportProducer,
    OutlookRulesSyncProducer,
    OutlookRulesPlanProducer,
    OutlookRulesDeleteProducer,
    OutlookRulesSweepProducer,
    OutlookCategoriesListProducer,
    OutlookCategoriesExportProducer,
    OutlookFoldersSyncProducer,
    OutlookCalendarAddProducer,
    OutlookCalendarAddRecurringProducer,
    OutlookCalendarAddFromConfigProducer,
)


# Re-export auth commands
__all__ = [
    'run_outlook_auth_device_code',
    'run_outlook_auth_poll',
    'run_outlook_auth_ensure',
    'run_outlook_auth_validate',
]


def run_outlook_rules_list(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookRulesListConsumer,
        OutlookRulesListProcessor,
        OutlookRulesListProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'use_cache': getattr(args, 'use_cache', False),
            'cache_ttl': getattr(args, 'cache_ttl', 600),
        },
    )


def run_outlook_rules_export(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookRulesExportConsumer,
        OutlookRulesExportProcessor,
        OutlookRulesExportProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'out_path': args.out,
            'use_cache': getattr(args, 'use_cache', False),
            'cache_ttl': getattr(args, 'cache_ttl', 600),
        },
    )


def run_outlook_rules_sync(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    if getattr(args, 'verbose', False):
        client_id, tenant, token_path, cache_dir = resolve_outlook_args(args)
        print(f"[outlook rules] client_id={client_id} tenant={tenant} token={token_path or '<memory>'} cache_dir={cache_dir or ''} dry_run={bool(args.dry_run)}")

    executor = OutlookCommandExecutor(
        OutlookRulesSyncConsumer,
        OutlookRulesSyncProcessor,
        OutlookRulesSyncProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'config_path': args.config,
            'dry_run': getattr(args, 'dry_run', False),
            'delete_missing': getattr(args, 'delete_missing', False),
            'move_to_folders': getattr(args, 'move_to_folders', False),
            'verbose': getattr(args, 'verbose', False),
        },
        producer_kwargs={
            'dry_run': getattr(args, 'dry_run', False),
            'delete_missing': getattr(args, 'delete_missing', False),
        },
    )


def run_outlook_rules_plan(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookRulesPlanConsumer,
        OutlookRulesPlanProcessor,
        OutlookRulesPlanProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'config_path': args.config,
            'move_to_folders': getattr(args, 'move_to_folders', False),
            'use_cache': getattr(args, 'use_cache', False),
            'cache_ttl': getattr(args, 'cache_ttl', 600),
        },
    )


def run_outlook_rules_delete(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookRulesDeleteConsumer,
        OutlookRulesDeleteProcessor,
        OutlookRulesDeleteProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={'rule_id': args.id},
    )


def run_outlook_rules_sweep(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookRulesSweepConsumer,
        OutlookRulesSweepProcessor,
        OutlookRulesSweepProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'config_path': args.config,
            'dry_run': getattr(args, 'dry_run', False),
            'move_to_folders': getattr(args, 'move_to_folders', False),
            'clear_cache': getattr(args, 'clear_cache', False),
            'days': getattr(args, 'days', 30),
            'top': getattr(args, 'top', 25),
            'pages': getattr(args, 'pages', 2),
        },
        producer_kwargs={'dry_run': getattr(args, 'dry_run', False)},
    )


def run_outlook_categories_list(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookCategoriesListConsumer,
        OutlookCategoriesListProcessor,
        OutlookCategoriesListProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'use_cache': getattr(args, 'use_cache', False),
            'cache_ttl': getattr(args, 'cache_ttl', 600),
        },
    )


def run_outlook_categories_export(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookCategoriesExportConsumer,
        OutlookCategoriesExportProcessor,
        OutlookCategoriesExportProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'out_path': args.out,
            'use_cache': getattr(args, 'use_cache', False),
            'cache_ttl': getattr(args, 'cache_ttl', 600),
        },
    )


def run_outlook_categories_sync(args) -> int:
    """Create/update Outlook categories from a labels YAML file."""
    client, err = get_outlook_client(args)
    if err:
        return err

    from ..yamlio import load_config
    from ..dsl import normalize_labels_for_outlook

    doc = load_config(args.config)
    base = doc.get("labels") or []
    desired = normalize_labels_for_outlook(base)

    existing = {lbl.get("name", ""): lbl for lbl in client.list_labels()}

    created = 0
    updated = 0
    dry_run = getattr(args, 'dry_run', False)

    for spec in desired:
        name = spec.get("name")
        if not name:
            continue
        if name not in existing:
            if dry_run:
                print(f"Would create category: {name}")
            else:
                client.create_label(**spec)
                print(f"Created category: {name}")
            created += 1
            continue
        # Update color if different/specified
        cur = existing[name]
        need = False
        upd = {"name": name}
        if spec.get("color") and spec.get("color") != cur.get("color"):
            upd["color"] = spec["color"]
            need = True
        if need:
            if dry_run:
                print(f"Would update category: {name}")
            else:
                client.update_label(cur.get("id", ""), upd)
                print(f"Updated category: {name}")
            updated += 1

    print(f"Sync complete. Created: {created}, Updated: {updated}")
    return 0


def run_outlook_folders_sync(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookFoldersSyncConsumer,
        OutlookFoldersSyncProcessor,
        OutlookFoldersSyncProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'config_path': args.config,
            'dry_run': getattr(args, 'dry_run', False),
        },
        producer_kwargs={'dry_run': getattr(args, 'dry_run', False)},
    )


def run_outlook_calendar_add(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookCalendarAddConsumer,
        OutlookCalendarAddProcessor,
        OutlookCalendarAddProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'subject': args.subject,
            'start_iso': args.start,
            'end_iso': args.end,
            'calendar_name': getattr(args, "calendar", None),
            'tz': getattr(args, "tz", None),
            'body_html': getattr(args, "body_html", None),
            'all_day': getattr(args, "all_day", False),
            'location': getattr(args, "location", None),
            'no_reminder': getattr(args, "no_reminder", False),
        },
    )


def run_outlook_calendar_add_recurring(args) -> int:
    if not (args.until or args.count):
        print("Provide either --until (YYYY-MM-DD) or --count for the recurrence range")
        return 2
    if args.repeat == "weekly" and not args.byday:
        print("For weekly recurrence, provide --byday like MO,WE,FR")
        return 2

    client, err = get_outlook_client(args)
    if err:
        return err

    byday = None
    if getattr(args, "byday", None):
        byday = [s.strip() for s in str(args.byday).split(',') if s.strip()]

    executor = OutlookCommandExecutor(
        OutlookCalendarAddRecurringConsumer,
        OutlookCalendarAddRecurringProcessor,
        OutlookCalendarAddRecurringProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'subject': args.subject,
            'start_time': args.start_time,
            'end_time': args.end_time,
            'repeat': args.repeat,
            'range_start': args.range_start,
            'calendar_name': getattr(args, "calendar", None),
            'tz': getattr(args, "tz", None),
            'interval': getattr(args, "interval", 1),
            'byday': byday,
            'until': getattr(args, "until", None),
            'count': getattr(args, "count", None),
            'body_html': getattr(args, "body_html", None),
            'location': getattr(args, "location", None),
            'exdates': [s.strip() for s in str(getattr(args, 'exdates', '') or '').split(',') if s.strip()] or None,
            'no_reminder': getattr(args, "no_reminder", False),
        },
    )


def run_outlook_messages_search(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    query = getattr(args, "query", "") or ""
    top = getattr(args, "top", 50) or 50
    pages = getattr(args, "pages", 3) or 3
    after = getattr(args, "after", None)
    sender = getattr(args, "sender", None)
    as_json = getattr(args, "json", False)
    only_inbox = getattr(args, "only_inbox", False)

    if not query and not sender:
        print("Provide --query or --sender to filter messages")
        return 1

    days = getattr(args, "days", None)
    if days and not after:
        import datetime
        after = (datetime.date.today() - datetime.timedelta(days=int(days))).isoformat()

    msgs = client.search_messages(query=query, top=top, pages=pages, after=after, sender=sender, only_inbox=only_inbox)

    if as_json:
        import json
        print(json.dumps(msgs, indent=2))
    else:
        for m in msgs:
            att = " 📎" if m.get("has_attachments") else ""
            print(f"[{m['received'][:10]}]{att} {m['subject']!r}  —  {m['from']}")
            if m.get("snippet"):
                print(f"   {m['snippet'][:120]}")
    return 0


def run_outlook_rules_prune_empty(args) -> int:
    """Delete Outlook inbox rules that have no conditions and no actions."""
    client, err = get_outlook_client(args)
    if err:
        return err

    dry_run = getattr(args, "dry_run", False)
    rules = client.list_filters()

    empty = [r for r in rules if not r.get("criteria") and not r.get("action")]
    if not empty:
        print("No empty rules found.")
        return 0

    deleted = 0
    for r in empty:
        rid = r.get("id")
        if not rid:
            continue
        if dry_run:
            print(f"Would delete empty rule: {rid}")
        else:
            client.delete_filter(rid)
            print(f"Deleted empty rule: {rid}")
        deleted += 1

    action = "Would delete" if dry_run else "Deleted"
    print(f"{action} {deleted} empty rule(s).")
    return 0


def run_outlook_messages_summarize(args) -> int:
    """Summarize an Outlook message identified by --id or --query."""
    import re
    from pathlib import Path

    client, err = get_outlook_client(args)
    if err:
        return err

    msg_id = getattr(args, "id", None)
    query = (getattr(args, "query", None) or "").strip()
    top = getattr(args, "top", 5) or 5
    pages = getattr(args, "pages", 1) or 1
    max_words = int(getattr(args, "max_words", 120) or 120)
    out_path = getattr(args, "out", None)

    if not msg_id:
        if not query:
            print("Provide --id or --query to identify a message")
            return 1
        results = client.search_messages(query=query, top=int(top), pages=int(pages))
        if not results:
            print("No message found matching query")
            return 1
        msg_id = results[0]["id"]

    msg = client.get_message(msg_id, select_body=True)
    body_content = (msg.get("body") or {}).get("content") or msg.get("bodyPreview") or ""
    text = re.sub(r"<[^>]+>", " ", body_content)
    text = re.sub(r"\s+", " ", text).strip()

    from ..llm_adapter import summarize_text
    summary = summarize_text(text, max_words=max_words)

    subject = msg.get("subject", "")
    received = (msg.get("receivedDateTime") or "")[:10]
    addr = (msg.get("from") or {}).get("emailAddress", {})
    from_str = f"{addr.get('name', '')} <{addr.get('address', '')}>"

    output = f"[{received}] {subject!r} from {from_str}\n{summary}"
    print(output)

    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(output + "\n", encoding="utf-8")
        print(f"Summary written to {out_path}")

    return 0


def run_outlook_calendar_add_from_config(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    executor = OutlookCommandExecutor(
        OutlookCalendarAddFromConfigConsumer,
        OutlookCalendarAddFromConfigProcessor,
        OutlookCalendarAddFromConfigProducer,
    )
    return executor.execute(
        client,
        consumer_kwargs={
            'config_path': args.config,
            'no_reminder': getattr(args, "no_reminder", False),
        },
    )
