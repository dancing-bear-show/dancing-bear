"""Config CLI commands for configuration, backup, cache, workflows, and env setup."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional


def _lazy_gmail_client():
    """Import and construct GmailClient lazily to avoid import errors on help."""
    try:
        from ..gmail_api import GmailClient
    except Exception as e:
        raise SystemExit(f"Gmail features unavailable: {e}")
    return GmailClient


def _load_config(path: Optional[str]) -> dict:
    """Load YAML config if available. Returns {} on any error."""
    if not path:
        return {}
    try:
        from ..yamlio import load_config as _load
        return _load(path)
    except Exception:
        return {}


def run_auth(args: argparse.Namespace) -> int:
    """Authenticate with Gmail."""
    from ..config_resolver import persist_if_provided, resolve_paths_profile
    creds_path, token_path = resolve_paths_profile(
        arg_credentials=getattr(args, "credentials", None),
        arg_token=getattr(args, "token", None),
        profile=getattr(args, 'profile', None),
    )

    if getattr(args, 'validate', False):
        # Non-interactive token validation for Gmail
        try:
            from google.auth.transport.requests import Request  # type: ignore
            from google.oauth2.credentials import Credentials  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
            from ..gmail_api import SCOPES as GMAIL_SCOPES  # type: ignore
        except Exception as e:
            print(f"Gmail validation unavailable (missing deps): {e}")
            return 1
        if not token_path or not os.path.exists(token_path):
            print(f"Token file not found: {token_path or '<unspecified>'}")
            return 2
        try:
            creds = Credentials.from_authorized_user_file(token_path, scopes=GMAIL_SCOPES)
            if creds and creds.expired and getattr(creds, 'refresh_token', None):
                creds.refresh(Request())
            svc = build("gmail", "v1", credentials=creds)
            _ = svc.users().getProfile(userId="me").execute()
            print("Gmail token valid.")
            return 0
        except Exception as e:
            print(f"Gmail token invalid: {e}")
            return 3

    GmailClient = _lazy_gmail_client()
    client = GmailClient(credentials_path=creds_path, token_path=token_path)
    client.authenticate()
    persist_if_provided(arg_credentials=getattr(args, "credentials", None), arg_token=getattr(args, "token", None))
    print("Authentication complete.")
    return 0


def run_backup(args: argparse.Namespace) -> int:
    """Backup Gmail labels and filters to a timestamped folder."""
    ts = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else Path("backups") / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    from ..utils.cli_helpers import gmail_provider_from_args
    client = gmail_provider_from_args(args)
    client.authenticate()
    # Labels
    labels = client.list_labels()
    labels_doc = {"labels": [
        {k: v for k, v in l.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
        for l in labels if l.get("type") != "system"
    ], "redirects": []}
    from ..yamlio import dump_config
    dump_config(str(out_dir / "labels.yaml"), labels_doc)
    # Filters
    id_to_name = {lab.get("id", ""): lab.get("name", "") for lab in labels}
    def ids_to_names(ids):
        return [id_to_name.get(x) for x in ids or [] if id_to_name.get(x)]
    filters = client.list_filters()
    dsl_filters = []
    for f in filters:
        crit = f.get("criteria", {}) or {}
        act = f.get("action", {}) or {}
        entry = {
            "match": {k: v for k, v in crit.items() if k in ("from","to","subject","query","negatedQuery","hasAttachment","size","sizeComparison") and v not in (None, "")},
            "action": {},
        }
        if act.get("forward"):
            entry["action"]["forward"] = act["forward"]
        if act.get("addLabelIds"):
            entry["action"]["add"] = ids_to_names(act.get("addLabelIds"))
        if act.get("removeLabelIds"):
            entry["action"]["remove"] = ids_to_names(act.get("removeLabelIds"))
        dsl_filters.append(entry)
    dump_config(str(out_dir / "filters.yaml"), {"filters": dsl_filters})
    print(f"Backup written to {out_dir}")
    return 0


def run_cache_stats(args: argparse.Namespace) -> int:
    """Show cache stats."""
    root = Path(args.cache)
    total = 0
    files = 0
    for p in root.rglob("*"):
        if p.is_file():
            files += 1
            try:
                total += p.stat().st_size
            except Exception:
                pass  # nosec B110 - non-critical stat failure
    print(f"Cache: {root} files={files} size={total} bytes")
    return 0


def run_cache_clear(args: argparse.Namespace) -> int:
    """Delete entire cache."""
    root = Path(args.cache)
    if not root.exists():
        print("Cache does not exist.")
        return 0
    import shutil
    shutil.rmtree(root)
    print(f"Cleared cache: {root}")
    return 0


def run_cache_prune(args: argparse.Namespace) -> int:
    """Prune files older than N days from cache."""
    root = Path(args.cache)
    if not root.exists():
        print("Cache does not exist.")
        return 0
    import time
    cutoff = time.time() - (int(args.days) * 86400)
    removed = 0
    for p in root.rglob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            pass  # nosec B110 - non-critical prune failure
    print(f"Pruned {removed} files older than {args.days} days from {root}")
    return 0


def run_config_inspect(args: argparse.Namespace) -> int:
    """Show config with redacted secrets."""
    import configparser
    from ..utils.shield import mask_value as _mask_value
    ini = Path(os.path.expanduser(args.path))
    if not ini.exists():
        print(f"Config not found: {ini}")
        return 2
    cp = configparser.ConfigParser()
    try:
        cp.read(ini)
    except Exception as e:
        print(f"Failed to read INI: {e}")
        return 3
    sections = cp.sections()
    if args.section:
        sections = [s for s in sections if s == args.section]
        if not sections:
            print(f"Section not found: {args.section}")
            return 4
    elif args.only_mail:
        sections = [s for s in sections if s.startswith("mail_assistant")]

    for s in sections:
        print(f"[{s}]")
        for k, v in cp.items(s):
            safe = _mask_value(k, v)
            print(f"{k} = {safe}")
        print("")
    return 0


def run_config_derive_labels(args: argparse.Namespace) -> int:
    """Derive Gmail and Outlook labels YAML from unified labels.yaml."""
    doc = _load_config(getattr(args, 'in_path', None))
    labels = doc.get("labels") or []
    if not isinstance(labels, list):
        print("Input missing labels: []")
        return 2
    from ..yamlio import dump_config
    # Gmail: pass-through
    out_g = Path(args.out_gmail)
    out_g.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_g), {"labels": labels})
    # Outlook: normalized names/colors
    from ..dsl import normalize_labels_for_outlook
    out_o = Path(args.out_outlook)
    out_o.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_o), {"labels": normalize_labels_for_outlook(labels)})
    print(f"Derived labels -> gmail:{out_g} outlook:{out_o}")
    return 0


def run_config_derive_filters(args: argparse.Namespace) -> int:
    """Derive Gmail and Outlook filters YAML from unified filters.yaml."""
    doc = _load_config(getattr(args, 'in_path', None))
    filters = doc.get("filters") or []
    if not isinstance(filters, list):
        print("Input missing filters: []")
        return 2
    from ..yamlio import dump_config
    # Gmail: pass-through
    out_g = Path(args.out_gmail)
    out_g.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_g), {"filters": filters})
    # Outlook: normalized subset; optionally encode moveToFolder from first add
    from ..dsl import normalize_filters_for_outlook
    out_specs = normalize_filters_for_outlook(filters)
    # If requested, when YAML removes INBOX, prefer Archive as destination on Outlook
    if getattr(args, 'outlook_archive_on_remove_inbox', False):
        for i, spec in enumerate(out_specs):
            a = spec.get("action") or {}
            try:
                orig = filters[i]
            except Exception:
                orig = {}
            orig_action = (orig or {}).get("action") or {}
            remove_list = orig_action.get("remove") or []
            if isinstance(remove_list, list) and any(str(x).upper() == 'INBOX' for x in remove_list):
                a["moveToFolder"] = "Archive"
                a.pop("add", None)
                spec["action"] = a
    elif getattr(args, 'outlook_move_to_folders', False):
        for spec in out_specs:
            a = spec.get("action") or {}
            adds = a.get("add") or []
            if adds and not a.get("moveToFolder"):
                a["moveToFolder"] = str(adds[0])
                spec["action"] = a
    out_o = Path(args.out_outlook)
    out_o.parent.mkdir(parents=True, exist_ok=True)
    dump_config(str(out_o), {"filters": out_specs})
    print(f"Derived filters -> gmail:{out_g} outlook:{out_o}")
    return 0


def run_config_optimize_filters(args: argparse.Namespace) -> int:
    """Merge rules with same destination label and simple from criteria."""
    doc = _load_config(getattr(args, 'in_path', None))
    rules = doc.get("filters") or []
    if not isinstance(rules, list):
        print("Input missing filters: []")
        return 2
    from collections import defaultdict
    groups = defaultdict(list)
    passthrough = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        m = r.get('match') or {}
        a = r.get('action') or {}
        adds = a.get('add') or []
        has_only_from = bool(m.get('from')) and all(k in (None, '') for k in [m.get('to'), m.get('subject'), m.get('query'), m.get('negatedQuery')])
        if adds and has_only_from:
            dest = str(adds[0])
            groups[dest].append(r)
        else:
            passthrough.append(r)

    merged = []
    preview = []
    threshold = max(2, int(getattr(args, 'merge_threshold', 2)))
    for dest, items in groups.items():
        if len(items) < threshold:
            passthrough.extend(items)
            continue
        terms = []
        removes = set()
        forwards = set()
        for it in items:
            m = it.get('match') or {}
            a = it.get('action') or {}
            frm = str(m.get('from') or '').strip()
            if frm:
                terms.append(frm)
            for x in a.get('remove') or []:
                removes.add(x)
            if a.get('forward'):
                forwards.add(str(a.get('forward')))
        atoms = []
        for t in terms:
            parts = [p.strip() for p in t.split('OR') if p.strip()]
            atoms.extend(parts)
        uniq = sorted({a for a in atoms})
        if not uniq:
            passthrough.extend(items)
            continue
        merged_rule = {
            'name': f'merged_{dest.replace("/","_")}',
            'match': {'from': ' OR '.join(uniq)},
            'action': {'add': [dest]},
        }
        if removes:
            merged_rule['action']['remove'] = sorted(removes)
        merged.append(merged_rule)
        preview.append((dest, len(items), len(uniq)))

    optimized = {'filters': merged + passthrough}
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    from ..yamlio import dump_config
    dump_config(str(outp), optimized)
    if getattr(args, 'preview', False):
        print('Merged groups:')
        for dest, n, u in sorted(preview, key=lambda x: -x[1]):
            print(f'- {dest}: merged {n} rules into 1 (unique from terms={u})')
    print(f"Optimized filters written to {outp}. Original={len(rules)} Optimized={len(optimized['filters'])}")
    return 0


def run_config_audit_filters(args: argparse.Namespace) -> int:
    """Report percentage of simple Gmail rules not present in unified config."""
    uni = _load_config(getattr(args, 'in_path', None))
    exp = _load_config(getattr(args, 'export_path', None))
    unified = uni.get('filters') or []
    exported = exp.get('filters') or []
    dest_to_from_tokens: dict[str, set[str]] = {}
    for f in unified:
        if not isinstance(f, dict):
            continue
        a = f.get('action') or {}
        adds = a.get('add') or []
        if not adds:
            continue
        dest = str(adds[0])
        m = f.get('match') or {}
        frm = str(m.get('from') or '')
        toks = {t.strip().lower() for t in frm.split('OR') if t.strip()}
        if not toks:
            continue
        dest_to_from_tokens.setdefault(dest, set()).update(toks)

    simple_total = 0
    covered = 0
    missing_samples: list[tuple[str, str]] = []
    for f in exported:
        if not isinstance(f, dict):
            continue
        c = f.get('criteria') or f.get('match') or {}
        a = f.get('action') or {}
        if any(k in c for k in ('query','negatedQuery','size','sizeComparison')):
            continue
        if c.get('to') or c.get('subject'):
            continue
        frm = str(c.get('from') or '').strip().lower()
        adds = a.get('addLabels') or a.get('add') or []
        if not adds and a.get('moveToFolder'):
            adds = [str(a.get('moveToFolder'))]
        if not frm or not adds:
            continue
        simple_total += 1
        dest = str(adds[0])
        toks = dest_to_from_tokens.get(dest) or set()
        cov = any((tok and (tok in frm or frm in tok)) for tok in toks)
        if cov:
            covered += 1
        elif len(missing_samples) < 10:
            missing_samples.append((dest, frm))

    not_cov = simple_total - covered
    pct = (not_cov / simple_total * 100.0) if simple_total else 0.0
    print(f"Simple Gmail rules: {simple_total}")
    print(f"Covered by unified: {covered}")
    print(f"Not unified: {not_cov} ({pct:.1f}%)")
    if getattr(args, 'preview_missing', False) and missing_samples:
        print("Missing examples (dest, from):")
        for dest, frm in missing_samples:
            print(f"- {dest} <- {frm}")
    return 0


def run_workflows_gmail_from_unified(args: argparse.Namespace) -> int:
    """Workflow: derive Gmail filters from unified, plan, and optionally apply."""
    from ..filters.commands import run_filters_plan, run_filters_sync
    out_dir = Path(getattr(args, 'out_dir', 'out'))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_gmail = out_dir / "filters.gmail.from_unified.yaml"
    out_outlook = out_dir / "filters.outlook.from_unified.yaml"

    # 1) Derive provider-specific configs from unified
    ns = argparse.Namespace(
        in_path=args.config,
        out_gmail=str(out_gmail),
        out_outlook=str(out_outlook),
        outlook_move_to_folders=True,
    )
    run_config_derive_filters(ns)

    # 2) Plan Gmail changes
    ns_plan = argparse.Namespace(
        config=str(out_gmail),
        delete_missing=bool(getattr(args, 'delete_missing', False)),
        credentials=None,
        token=None,
        cache=None,
        profile=getattr(args, 'profile', None),
    )
    print("\n[Plan] Gmail filters vs derived from unified:")
    run_filters_plan(ns_plan)

    # 3) Optionally apply
    if getattr(args, 'apply', False):
        ns_sync = argparse.Namespace(
            config=str(out_gmail),
            dry_run=False,
            delete_missing=bool(getattr(args, 'delete_missing', False)),
            require_forward_verified=False,
            credentials=None,
            token=None,
            cache=None,
            profile=getattr(args, 'profile', None),
        )
        print("\n[Apply] Syncing Gmail filters to match derived …")
        run_filters_sync(ns_sync)
        print("\nDone. Consider exporting and comparing for drift:")
        print(f"  python3 -m mail_assistant filters export --out {out_dir}/filters.gmail.export.after.yaml")
        print(f"  Compare to {out_gmail}")
    else:
        print("\nNo changes applied (omit --apply to keep planning only).")
    return 0


def run_env_setup(args: argparse.Namespace) -> int:
    """Create venv, install package, and persist credentials to INI."""
    from ..config_resolver import (
        default_gmail_credentials_path,
        default_gmail_token_path,
        expand_path,
        persist_profile_settings,
    )
    venv_dir = Path(getattr(args, 'venv_dir', '.venv'))
    if not getattr(args, 'no_venv', False):
        try:
            if not venv_dir.exists():
                print(f"Creating venv at {venv_dir} …")
                __import__('venv').EnvBuilder(with_pip=True).create(str(venv_dir))
            if not getattr(args, 'skip_install', False):
                py = venv_dir / 'bin' / 'python'
                import subprocess
                print("Upgrading pip …")
                subprocess.run([str(py), '-m', 'pip', 'install', '-U', 'pip'], check=True)
                print("Installing package in editable mode …")
                subprocess.run([str(py), '-m', 'pip', 'install', '-e', '.'], check=True)
        except Exception as e:
            print(f"Venv/setup failed: {e}")
            return 2
        for fname in ('bin/mail_assistant', 'bin/mail-assistant'):
            try:
                p = Path(fname)
                if p.exists():
                    os.chmod(p, (p.stat().st_mode | 0o111))
            except Exception:
                pass  # nosec B110 - non-critical chmod failure

    prof = getattr(args, 'profile', None)
    cred_path = getattr(args, 'credentials', None)
    tok_path = getattr(args, 'token', None)

    if getattr(args, 'copy_gmail_example', False) and not cred_path:
        ex = Path('credentials.example.json')
        dest = Path(expand_path(default_gmail_credentials_path()))
        if ex.exists() and not dest.exists():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(ex.read_text(encoding='utf-8'), encoding='utf-8')
                cred_path = str(dest)
                print(f"Copied {ex} → {dest}")
            except Exception as e:
                print(f"Warning: failed to copy example credentials: {e}")
    if cred_path and not tok_path:
        tok_path = default_gmail_token_path()

    for pth in (cred_path, tok_path, getattr(args, 'outlook_token', None)):
        if pth:
            try:
                Path(os.path.expanduser(pth)).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass  # nosec B110 - non-critical mkdir failure

    if any([cred_path, tok_path, getattr(args, 'outlook_client_id', None), getattr(args, 'tenant', None), getattr(args, 'outlook_token', None)]):
        persist_profile_settings(
            profile=prof,
            credentials=cred_path,
            token=tok_path,
            outlook_client_id=getattr(args, 'outlook_client_id', None),
            tenant=getattr(args, 'tenant', None),
            outlook_token=getattr(args, 'outlook_token', None),
        )
        print("Persisted settings to ~/.config/credentials.ini")
    else:
        print("No profile settings provided; skipped INI write.")

    print("Environment setup complete.")
    return 0


def run_workflows_from_unified(args: argparse.Namespace) -> int:
    """Workflow: derive provider configs from unified and plan/apply per provider."""
    from ..filters.commands import run_filters_plan, run_filters_sync
    from ..outlook.commands import run_outlook_rules_plan, run_outlook_rules_sync
    from ..outlook.helpers import resolve_outlook_args as _resolve_outlook_args
    out_dir = Path(getattr(args, 'out_dir', 'out'))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_gmail = out_dir / "filters.gmail.from_unified.yaml"
    out_outlook = out_dir / "filters.outlook.from_unified.yaml"

    # 0) Derive both provider configs from unified
    ns = argparse.Namespace(
        in_path=args.config,
        out_gmail=str(out_gmail),
        out_outlook=str(out_outlook),
        outlook_move_to_folders=bool(getattr(args, 'outlook_move_to_folders', True)),
    )
    run_config_derive_filters(ns)

    # 1) Decide providers
    requested = None
    if getattr(args, 'providers', None):
        requested = {p.strip().lower() for p in str(args.providers).split(',') if p.strip()}

    run_gmail = run_outlook = False
    if requested is None or 'gmail' in requested:
        try:
            from ..config_resolver import resolve_paths_profile
            cpath, tpath = resolve_paths_profile(arg_credentials=None, arg_token=None, profile=getattr(args, 'profile', None))
            cpath = os.path.expanduser(cpath or '')
            tpath = os.path.expanduser(tpath or '')
            if os.path.exists(cpath) or os.path.exists(tpath):
                run_gmail = True
        except Exception:
            run_gmail = False
        if requested and 'gmail' in requested:
            run_gmail = True

    if requested is None or 'outlook' in requested:
        try:
            oargs = argparse.Namespace(
                client_id=None,
                tenant=None,
                token=None,
                accounts_config=getattr(args, 'accounts_config', None),
                account=getattr(args, 'account', None),
                profile=getattr(args, 'profile', None),
            )
            cid, _ten, _tok, _cache = _resolve_outlook_args(oargs)
            if cid:
                run_outlook = True
        except Exception:
            run_outlook = False
        if requested and 'outlook' in requested:
            run_outlook = True

    # 2) Gmail plan/apply
    if run_gmail:
        print("\n[Gmail] Plan:")
        ns_plan = argparse.Namespace(
            config=str(out_gmail),
            delete_missing=bool(getattr(args, 'delete_missing', False)),
            credentials=None,
            token=None,
            cache=None,
            profile=getattr(args, 'profile', None),
        )
        run_filters_plan(ns_plan)
        if getattr(args, 'apply', False):
            print("\n[Gmail] Apply:")
            ns_sync = argparse.Namespace(
                config=str(out_gmail),
                dry_run=False,
                delete_missing=bool(getattr(args, 'delete_missing', False)),
                require_forward_verified=False,
                credentials=None,
                token=None,
                cache=None,
                profile=getattr(args, 'profile', None),
            )
            run_filters_sync(ns_sync)
    else:
        if requested is None or 'gmail' in (requested or set(['gmail'])):
            print("\n[Gmail] Skipping (no credentials/token detected). Use --profile or env setup.")

    # 3) Outlook plan/apply
    if run_outlook:
        print("\n[Outlook] Plan:")
        ns_pl = argparse.Namespace(
            config=str(out_outlook),
            client_id=None,
            tenant=None,
            token=None,
            accounts_config=getattr(args, 'accounts_config', None),
            account=getattr(args, 'account', None),
            profile=getattr(args, 'profile', None),
            use_cache=False,
            cache_ttl=600,
        )
        run_outlook_rules_plan(ns_pl)
        if getattr(args, 'apply', False):
            print("\n[Outlook] Apply:")
            ns_sync = argparse.Namespace(
                config=str(out_outlook),
                client_id=None,
                tenant=None,
                token=None,
                accounts_config=getattr(args, 'accounts_config', None),
                account=getattr(args, 'account', None),
                profile=getattr(args, 'profile', None),
                dry_run=False,
                delete_missing=bool(getattr(args, 'delete_missing', False)),
                move_to_folders=bool(getattr(args, 'outlook_move_to_folders', True)),
            )
            run_outlook_rules_sync(ns_sync)
    else:
        if requested is None or 'outlook' in (requested or set(['outlook'])):
            print("\n[Outlook] Skipping (no client_id/token detected). Use env setup or accounts.yaml.")

    if not (run_gmail or run_outlook):
        print("No configured providers detected; nothing to do.")
        return 2
    return 0
