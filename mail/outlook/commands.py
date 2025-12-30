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
