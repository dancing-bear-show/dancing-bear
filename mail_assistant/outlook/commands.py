from __future__ import annotations

"""Convenience orchestration helpers for Outlook commands."""

import json
from pathlib import Path

from ..config_resolver import expand_path, default_outlook_token_path
from core.auth import resolve_outlook_credentials
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


def run_outlook_rules_list(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookRulesListConsumer(
        client=client,
        use_cache=getattr(args, 'use_cache', False),
        cache_ttl=getattr(args, 'cache_ttl', 600),
    )
    processor = OutlookRulesListProcessor()
    producer = OutlookRulesListProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_rules_export(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookRulesExportConsumer(
        client=client,
        out_path=args.out,
        use_cache=getattr(args, 'use_cache', False),
        cache_ttl=getattr(args, 'cache_ttl', 600),
    )
    processor = OutlookRulesExportProcessor()
    producer = OutlookRulesExportProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_rules_sync(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    if getattr(args, 'verbose', False):
        client_id, tenant, token_path, cache_dir = resolve_outlook_args(args)
        print(f"[outlook rules] client_id={client_id} tenant={tenant} token={token_path or '<memory>'} cache_dir={cache_dir or ''} dry_run={bool(args.dry_run)}")

    consumer = OutlookRulesSyncConsumer(
        client=client,
        config_path=args.config,
        dry_run=getattr(args, 'dry_run', False),
        delete_missing=getattr(args, 'delete_missing', False),
        move_to_folders=getattr(args, 'move_to_folders', False),
        verbose=getattr(args, 'verbose', False),
    )
    processor = OutlookRulesSyncProcessor()
    producer = OutlookRulesSyncProducer(
        dry_run=getattr(args, 'dry_run', False),
        delete_missing=getattr(args, 'delete_missing', False),
    )

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_rules_plan(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookRulesPlanConsumer(
        client=client,
        config_path=args.config,
        move_to_folders=getattr(args, 'move_to_folders', False),
        use_cache=getattr(args, 'use_cache', False),
        cache_ttl=getattr(args, 'cache_ttl', 600),
    )
    processor = OutlookRulesPlanProcessor()
    producer = OutlookRulesPlanProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_rules_delete(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookRulesDeleteConsumer(client=client, rule_id=args.id)
    processor = OutlookRulesDeleteProcessor()
    producer = OutlookRulesDeleteProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 3))


def run_outlook_rules_sweep(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookRulesSweepConsumer(
        client=client,
        config_path=args.config,
        dry_run=getattr(args, 'dry_run', False),
        move_to_folders=getattr(args, 'move_to_folders', False),
        clear_cache=getattr(args, 'clear_cache', False),
        days=getattr(args, 'days', 30),
        top=getattr(args, 'top', 25),
        pages=getattr(args, 'pages', 2),
    )
    processor = OutlookRulesSweepProcessor()
    producer = OutlookRulesSweepProducer(dry_run=getattr(args, 'dry_run', False))

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_categories_list(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookCategoriesListConsumer(
        client=client,
        use_cache=getattr(args, 'use_cache', False),
        cache_ttl=getattr(args, 'cache_ttl', 600),
    )
    processor = OutlookCategoriesListProcessor()
    producer = OutlookCategoriesListProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_categories_export(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookCategoriesExportConsumer(
        client=client,
        out_path=args.out,
        use_cache=getattr(args, 'use_cache', False),
        cache_ttl=getattr(args, 'cache_ttl', 600),
    )
    processor = OutlookCategoriesExportProcessor()
    producer = OutlookCategoriesExportProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


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

    existing = {l.get("name", ""): l for l in client.list_labels()}

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

    consumer = OutlookFoldersSyncConsumer(
        client=client,
        config_path=args.config,
        dry_run=getattr(args, 'dry_run', False),
    )
    processor = OutlookFoldersSyncProcessor()
    producer = OutlookFoldersSyncProducer(dry_run=getattr(args, 'dry_run', False))

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


def run_outlook_calendar_add(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookCalendarAddConsumer(
        client=client,
        subject=args.subject,
        start_iso=args.start,
        end_iso=args.end,
        calendar_name=getattr(args, "calendar", None),
        tz=getattr(args, "tz", None),
        body_html=getattr(args, "body_html", None),
        all_day=getattr(args, "all_day", False),
        location=getattr(args, "location", None),
        no_reminder=getattr(args, "no_reminder", False),
    )
    processor = OutlookCalendarAddProcessor()
    producer = OutlookCalendarAddProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 3))


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

    consumer = OutlookCalendarAddRecurringConsumer(
        client=client,
        subject=args.subject,
        start_time=args.start_time,
        end_time=args.end_time,
        repeat=args.repeat,
        range_start=args.range_start,
        calendar_name=getattr(args, "calendar", None),
        tz=getattr(args, "tz", None),
        interval=getattr(args, "interval", 1),
        byday=byday,
        until=getattr(args, "until", None),
        count=getattr(args, "count", None),
        body_html=getattr(args, "body_html", None),
        location=getattr(args, "location", None),
        exdates=[s.strip() for s in str(getattr(args, 'exdates', '') or '').split(',') if s.strip()] or None,
        no_reminder=getattr(args, "no_reminder", False),
    )
    processor = OutlookCalendarAddRecurringProcessor()
    producer = OutlookCalendarAddRecurringProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 3))


def run_outlook_calendar_add_from_config(args) -> int:
    client, err = get_outlook_client(args)
    if err:
        return err

    consumer = OutlookCalendarAddFromConfigConsumer(
        client=client,
        config_path=args.config,
        no_reminder=getattr(args, "no_reminder", False),
    )
    processor = OutlookCalendarAddFromConfigProcessor()
    producer = OutlookCalendarAddFromConfigProducer()

    payload = consumer.consume()
    envelope = processor.process(payload)
    producer.produce(envelope)
    return 0 if envelope.ok() else int((envelope.diagnostics or {}).get("code", 1))


# Auth commands - These don't follow the pipeline pattern due to their interactive nature


def run_outlook_auth_device_code(args) -> int:
    """Start device code flow for Outlook authentication."""
    client_id, tenant, _ = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        None,
    )
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID, or store outlook_client_id in credentials.ini.")
        return 2

    try:
        import msal
    except Exception as e:
        print(f"Missing msal dependency: {e}. Run: pip install msal")
        return 1

    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id, authority=authority)
    flow = app.initiate_device_flow(scopes=["https://graph.microsoft.com/.default"])
    if "user_code" not in flow:
        print("Failed to start device flow.")
        return 1

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    flow_out = dict(flow)
    flow_out["_client_id"] = client_id
    flow_out["_tenant"] = tenant
    outp.write_text(json.dumps(flow_out), encoding="utf-8")

    msg = flow.get("message") or f"To sign in, visit {flow.get('verification_uri')} and enter code: {flow.get('user_code')}"
    print(msg)

    prof = getattr(args, 'profile', None)
    prof_flag = f" --profile {prof}" if prof else ""
    print(f"Next: ./bin/mail-assistant{prof_flag} outlook auth poll --flow {args.out} --token {default_outlook_token_path()}")

    if getattr(args, 'verbose', False):
        print(f"[device-code] Saved flow to {outp} (client_id={client_id}, tenant={tenant}).")
    print(f"Saved device flow to {outp}")
    return 0


def run_outlook_auth_poll(args) -> int:
    """Poll device code flow and save token."""
    try:
        import msal
    except Exception as e:
        print(f"Missing msal dependency: {e}. Run: pip install msal")
        return 1

    flow_path = Path(expand_path(args.flow))
    if not flow_path.exists():
        print(f"Device flow file not found: {flow_path}")
        return 2

    flow = json.loads(flow_path.read_text())
    client_id = flow.get("_client_id")
    tenant = flow.get("_tenant") or "consumers"
    if not client_id:
        print("Device flow missing _client_id. Re-run outlook auth device-code.")
        return 2

    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)

    if getattr(args, 'verbose', False):
        print(f"[device-code] Polling device flow from {flow_path}. This may take up to {int(flow.get('expires_in', 900))//60} minutes…")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print(f"Device flow failed: {result}")
        return 3

    token_path = Path(expand_path(args.token))
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(cache.serialize(), encoding="utf-8")
    print(f"Saved Outlook token cache to {token_path}")
    return 0


def run_outlook_auth_ensure(args) -> int:
    """Ensure a persistent Outlook MSAL token cache exists and is valid."""
    try:
        import msal
    except Exception as e:
        print(f"Missing msal dependency: {e}. Run: pip install msal")
        return 1

    client_id, tenant, token_path = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token_path = expand_path(token_path or default_outlook_token_path())
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID or configure a profile in ~/.config/credentials.ini")
        return 2

    cache = msal.SerializableTokenCache()
    tp = Path(token_path)
    if tp.exists():
        try:
            cache.deserialize(tp.read_text(encoding="utf-8"))
        except Exception:
            pass

    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)
    scopes = ["https://graph.microsoft.com/.default"]

    accounts = []
    try:
        accounts = app.get_accounts()
    except Exception:
        accounts = []

    if accounts:
        res = app.acquire_token_silent(scopes, account=accounts[0])
        if res and "access_token" in res:
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(cache.serialize(), encoding="utf-8")
            print(f"Token cache valid. Saved to {tp}")
            return 0

    # Fallback: interactive device flow
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        print("Failed to start device flow.")
        return 1

    msg = flow.get("message") or f"To sign in, visit {flow.get('verification_uri')} and enter code: {flow.get('user_code')}"
    print(msg)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print(f"Device flow failed: {result}")
        return 3

    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(cache.serialize(), encoding="utf-8")
    print(f"Saved Outlook token cache to {tp}")
    return 0


def run_outlook_auth_validate(args) -> int:
    """Validate Outlook token cache by performing a silent refresh and a /me ping."""
    try:
        import msal
        import requests
    except Exception as e:
        print(f"Outlook validation unavailable (missing deps): {e}")
        return 1

    client_id, tenant, token_path = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token_path = expand_path(token_path or default_outlook_token_path())
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID or configure a profile in ~/.config/credentials.ini")
        return 2

    tp = Path(token_path)
    if not tp.exists():
        print(f"Token cache not found: {tp}")
        return 2

    cache = msal.SerializableTokenCache()
    try:
        cache.deserialize(tp.read_text(encoding="utf-8"))
    except Exception:
        print(f"Unable to read token cache: {tp}")
        return 3

    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)

    accounts = []
    try:
        accounts = app.get_accounts()
    except Exception:
        accounts = []

    if not accounts:
        print("No account in token cache.")
        return 3

    res = app.acquire_token_silent(["https://graph.microsoft.com/.default"], account=accounts[0])
    if not (res and res.get("access_token")):
        print("Silent token acquisition failed.")
        return 4

    # Ping /me to confirm validity
    r = requests.get("https://graph.microsoft.com/v1.0/me", headers={"Authorization": f"Bearer {res['access_token']}"})
    if r.status_code == 200:
        print("Outlook token valid.")
        return 0

    print(f"Graph /me failed: {r.status_code} {r.text[:200]}")
    return 5
