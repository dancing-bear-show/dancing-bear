from __future__ import annotations

"""Accounts command orchestration helpers for multi-account operations."""

import argparse
from pathlib import Path

from ..yamlio import load_config
from .helpers import (
    load_accounts,
    iter_accounts,
    build_client_for_account,
    build_provider_for_account,
)


def run_accounts_list(args) -> int:
    """List all configured accounts."""
    accts = load_accounts(args.config)
    for a in accts:
        print(f"{a.get('name','<noname>')}\tprovider={a.get('provider')}\tcred={a.get('credentials','')}\ttoken={a.get('token','')}")
    return 0


def run_accounts_export_labels(args) -> int:
    """Export labels from all accounts to YAML files."""
    accts = load_accounts(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in iter_accounts(accts, args.accounts):
        client = build_provider_for_account(a)
        client.authenticate()
        labels = client.list_labels()
        doc = {"labels": [
            {k: v for k, v in l.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
            for l in labels if l.get("type") != "system"
        ], "redirects": []}
        path = out_dir / f"labels_{a.get('name','account')}.yaml"
        from ..yamlio import dump_config
        dump_config(str(path), doc)
        print(f"Exported labels for {a.get('name')}: {path}")
    return 0


def run_accounts_sync_labels(args) -> int:
    """Sync labels to all accounts from a YAML config."""
    from ..dsl import normalize_labels_for_outlook

    accts = load_accounts(args.config)
    for a in iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        print(f"[labels sync] account={a.get('name')} provider={provider}")
        client = build_provider_for_account(a)
        client.authenticate()
        desired_doc = load_config(args.labels)
        desired = desired_doc.get("labels") or []
        if provider == "outlook":
            desired = normalize_labels_for_outlook(desired)
        existing = {l.get("name", ""): l for l in client.list_labels()}
        for spec in desired:
            name = spec.get("name")
            if not name:
                continue
            if name not in existing:
                if args.dry_run:
                    print(f"  would create label: {name}")
                else:
                    client.create_label(**spec)
                    print(f"  created label: {name}")
            else:
                # Prepare update if any supported field differs
                upd = {"name": name}
                cur = existing[name]
                changed = False
                if provider == "gmail":
                    for k in ("color", "labelListVisibility", "messageListVisibility"):
                        if spec.get(k) and spec.get(k) != cur.get(k):
                            upd[k] = spec[k]
                            changed = True
                elif provider == "outlook":
                    if spec.get("color") and spec.get("color") != cur.get("color"):
                        upd["color"] = spec["color"]
                        changed = True
                if changed:
                    if args.dry_run:
                        print(f"  would update label: {name}")
                    else:
                        client.update_label(cur.get("id", ""), upd)
                        print(f"  updated label: {name}")
    return 0


def run_accounts_export_filters(args) -> int:
    """Export filters from all accounts to YAML files."""
    accts = load_accounts(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in iter_accounts(accts, args.accounts):
        client = build_provider_for_account(a)
        client.authenticate()
        # Map label IDs to names
        id_to_name = {lab.get("id", ""): lab.get("name", "") for lab in client.list_labels()}

        def ids_to_names(ids):
            return [id_to_name.get(x) for x in ids or [] if id_to_name.get(x)]

        dsl = []
        for f in client.list_filters():
            crit = f.get("criteria", {}) or {}
            act = f.get("action", {}) or {}
            entry = {
                "match": {k: v for k, v in crit.items() if k in ("from", "to", "subject", "query", "negatedQuery", "hasAttachment", "size", "sizeComparison") and v not in (None, "")},
                "action": {},
            }
            if act.get("forward"):
                entry["action"]["forward"] = act["forward"]
            if act.get("addLabelIds"):
                entry["action"]["add"] = ids_to_names(act.get("addLabelIds"))
            if act.get("removeLabelIds"):
                entry["action"]["remove"] = ids_to_names(act.get("removeLabelIds"))
            dsl.append(entry)
        path = out_dir / f"filters_{a.get('name','account')}.yaml"
        from ..yamlio import dump_config
        dump_config(str(path), {"filters": dsl})
        print(f"Exported filters for {a.get('name')}: {path}")
    return 0


def run_accounts_sync_filters(args) -> int:
    """Sync filters to all accounts from a YAML config."""
    from ..dsl import normalize_filters_for_outlook
    from ..filters.commands import run_filters_sync
    from ..outlook.helpers import norm_label_name_outlook

    accts = load_accounts(args.config)
    for a in iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        print(f"[filters sync] account={a.get('name')} provider={provider}")
        if provider == "gmail":
            ns = argparse.Namespace(
                credentials=a.get("credentials"),
                token=a.get("token"),
                cache=a.get("cache"),
                config=args.filters,
                dry_run=args.dry_run,
                delete_missing=False,
                require_forward_verified=args.require_forward_verified,
            )
            run_filters_sync(ns)
            continue

        if provider == "outlook":
            client = build_client_for_account(a)
            client.authenticate()
            doc = load_config(args.filters)
            desired = normalize_filters_for_outlook(doc.get("filters") or [])

            # Build canonical keys for comparison
            def canon(f: dict) -> str:
                crit = f.get("criteria") or {}
                act = f.get("action") or {}
                return str({
                    "from": crit.get("from"),
                    "to": crit.get("to"),
                    "subject": crit.get("subject"),
                    "add": tuple(sorted(act.get("addLabelIds", []) or [])),
                    "forward": act.get("forward"),
                })

            existing = {canon(f): f for f in client.list_filters()}
            # label name -> id map for assignCategories
            name_to_id = client.get_label_id_map()
            created = 0
            for spec in desired:
                m = spec.get("match") or {}
                a_act = spec.get("action") or {}
                criteria = {k: v for k, v in m.items() if k in ("from", "to", "subject")}
                action = {}
                if a_act.get("add"):
                    action["addLabelIds"] = [name_to_id.get(x) or name_to_id.get(norm_label_name_outlook(x)) for x in a_act["add"]]
                    action["addLabelIds"] = [x for x in action["addLabelIds"] if x]
                if a_act.get("forward"):
                    action["forward"] = a_act["forward"]
                key = str({
                    "from": criteria.get("from"),
                    "to": criteria.get("to"),
                    "subject": criteria.get("subject"),
                    "add": tuple(sorted(action.get("addLabelIds", []) or [])),
                    "forward": action.get("forward"),
                })
                if key in existing:
                    continue
                if args.dry_run:
                    print(f"  would create rule: criteria={criteria} action={action}")
                else:
                    try:
                        client.create_filter(criteria, action)
                        print("  created rule")
                    except Exception as e:
                        # Attempt to show Graph error body for easier troubleshooting
                        resp = getattr(e, 'response', None)
                        body = ''
                        try:
                            if resp is not None and hasattr(resp, 'text'):
                                body = resp.text
                        except Exception:
                            body = ''
                        print(f"  error creating rule: {e}{(' | ' + body) if body else ''}")
                created += 1
            print(f"  plan summary: created={created}")
            continue
        print(f"  provider not supported for filters: {provider}")
    return 0


def run_accounts_plan_labels(args) -> int:
    """Plan labels changes for all accounts."""
    from ..dsl import normalize_labels_for_outlook

    accts = load_accounts(args.config)
    desired_doc = load_config(args.labels)
    base = desired_doc.get("labels") or []
    for a in iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        client = build_provider_for_account(a)
        client.authenticate()
        existing = {l.get("name", ""): l for l in client.list_labels(use_cache=True)}
        target = base
        if provider == "outlook":
            target = normalize_labels_for_outlook(base)
        to_create = []
        to_update = []
        for spec in target:
            name = spec.get("name")
            if not name:
                continue
            if name not in existing:
                to_create.append(name)
            else:
                cur = existing[name]
                if provider == "gmail":
                    for k in ("color", "labelListVisibility", "messageListVisibility"):
                        if spec.get(k) and spec.get(k) != cur.get(k):
                            to_update.append(name)
                            break
                elif provider == "outlook":
                    if spec.get("color") and spec.get("color") != cur.get("color"):
                        to_update.append(name)
        print(f"[plan-labels] {a.get('name')} provider={provider} create={len(to_create)} update={len(to_update)}")
    return 0


def run_accounts_plan_filters(args) -> int:
    """Plan filters changes for all accounts."""
    from ..dsl import normalize_filters_for_outlook

    accts = load_accounts(args.config)
    desired_doc = load_config(args.filters)
    base = desired_doc.get("filters") or []
    for a in iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        client = build_provider_for_account(a)
        client.authenticate()
        existing = client.list_filters(use_cache=True)
        if provider == "gmail":
            # Canonicalize
            def canon(f: dict) -> str:
                crit = f.get("criteria") or {}
                act = f.get("action") or {}
                return str({
                    "from": crit.get("from"),
                    "to": crit.get("to"),
                    "subject": crit.get("subject"),
                    "query": crit.get("query"),
                    "add": tuple(sorted((act.get("addLabelIds") or []))),
                    "forward": act.get("forward"),
                })

            ex_keys = {canon(f) for f in existing}
            desired_keys = set()
            for f in base:
                m = f.get("match") or {}
                a_act = f.get("action") or {}
                desired_keys.add(str({
                    "from": m.get("from"),
                    "to": m.get("to"),
                    "subject": m.get("subject"),
                    "query": m.get("query"),
                    "add": tuple(sorted((a_act.get("add") or []))),
                    "forward": a_act.get("forward"),
                }))
            create = len([k for k in desired_keys if k not in ex_keys])
            print(f"[plan-filters] {a.get('name')} provider=gmail create={create}")
        elif provider == "outlook":
            desired = normalize_filters_for_outlook(base)

            def canon_o(f: dict) -> str:
                crit = f.get("criteria") or {}
                act = f.get("action") or {}
                return str({
                    "from": crit.get("from"),
                    "to": crit.get("to"),
                    "subject": crit.get("subject"),
                    "add": tuple(sorted((act.get("addLabelIds") or []))),
                    "forward": act.get("forward"),
                })

            ex_keys = {canon_o(f) for f in existing}
            desired_keys = set()
            for f in desired:
                m = f.get("match") or {}
                a_act = f.get("action") or {}
                desired_keys.add(str({
                    "from": m.get("from"),
                    "to": m.get("to"),
                    "subject": m.get("subject"),
                    "add": tuple(sorted((a_act.get("add") or []))),
                    "forward": a_act.get("forward"),
                }))
            create = len([k for k in desired_keys if k not in ex_keys])
            print(f"[plan-filters] {a.get('name')} provider=outlook create={create}")
        else:
            print(f"[plan-filters] {a.get('name')} provider={provider} not supported")
    return 0


def run_accounts_export_signatures(args) -> int:
    """Export signatures from all accounts to YAML files."""
    accts = load_accounts(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in iter_accounts(accts, args.accounts):
        name = a.get("name", "account")
        provider = (a.get("provider") or "").lower()
        path = out_dir / f"signatures_{name}.yaml"
        assets = out_dir / f"{name}_assets"
        assets.mkdir(parents=True, exist_ok=True)
        doc = {"signatures": {"gmail": [], "ios": {}, "outlook": []}}
        if provider == "gmail":
            client = build_provider_for_account(a)
            client.authenticate()
            sigs = client.list_signatures()
            doc["signatures"]["gmail"] = [
                {
                    "sendAs": s.get("sendAsEmail"),
                    "isPrimary": s.get("isPrimary", False),
                    "signature_html": s.get("signature", ""),
                }
                for s in sigs
            ]
            prim = next((s for s in doc["signatures"]["gmail"] if s.get("isPrimary")), None)
            if prim and prim.get("signature_html"):
                doc["signatures"]["default_html"] = prim["signature_html"]
                (assets / "ios_signature.html").write_text(prim["signature_html"], encoding="utf-8")
        elif provider == "outlook":
            # Not available via Graph; write guidance file
            (assets / "OUTLOOK_README.txt").write_text(
                "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                "Use ios_signature.html exported from a Gmail account, or paste HTML manually.",
                encoding="utf-8",
            )
        from ..yamlio import dump_config
        dump_config(str(path), doc)
        print(f"Exported signatures for {name}: {path}")
    return 0


def run_accounts_sync_signatures(args) -> int:
    """Sync signatures to all accounts from a YAML config."""
    from ..signatures.commands import run_signatures_sync

    accts = load_accounts(args.config)
    for a in iter_accounts(accts, args.accounts):
        provider = (a.get("provider") or "").lower()
        print(f"[signatures sync] account={a.get('name')} provider={provider}")
        if provider == "gmail":
            ns = argparse.Namespace(
                credentials=a.get("credentials"),
                token=a.get("token"),
                config=args.config,
                send_as=args.send_as,
                dry_run=args.dry_run,
                account_display_name=a.get("display_name"),
            )
            run_signatures_sync(ns)
        elif provider == "outlook":
            # Not supported via API; drop guidance file only
            assets = Path("signatures_assets")
            assets.mkdir(parents=True, exist_ok=True)
            (assets / "OUTLOOK_README.txt").write_text(
                "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                "Use ios_signature.html or paste HTML manually.",
                encoding="utf-8",
            )
            print("  Outlook: wrote guidance to signatures_assets/OUTLOOK_README.txt")
        else:
            print(f"  Unsupported provider: {provider}")
    return 0
