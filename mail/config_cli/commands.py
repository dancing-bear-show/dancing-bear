"""Config CLI commands for configuration, backup, cache, workflows, and env setup."""
from __future__ import annotations

import argparse
from typing import Optional

from .pipeline import (
    AuthRequest,
    AuthRequestConsumer,
    AuthProcessor,
    AuthProducer,
    BackupRequest,
    BackupRequestConsumer,
    BackupProcessor,
    BackupProducer,
    CacheStatsRequest,
    CacheStatsRequestConsumer,
    CacheStatsProcessor,
    CacheStatsProducer,
    CacheClearRequest,
    CacheClearRequestConsumer,
    CacheClearProcessor,
    CacheClearProducer,
    CachePruneRequest,
    CachePruneRequestConsumer,
    CachePruneProcessor,
    CachePruneProducer,
    ConfigInspectRequest,
    ConfigInspectRequestConsumer,
    ConfigInspectProcessor,
    ConfigInspectProducer,
    DeriveLabelsRequest,
    DeriveLabelsRequestConsumer,
    DeriveLabelsProcessor,
    DeriveLabelsProducer,
    DeriveFiltersRequest,
    DeriveFiltersRequestConsumer,
    DeriveFiltersProcessor,
    DeriveFiltersProducer,
    OptimizeFiltersRequest,
    OptimizeFiltersRequestConsumer,
    OptimizeFiltersProcessor,
    OptimizeFiltersProducer,
    AuditFiltersRequest,
    AuditFiltersRequestConsumer,
    AuditFiltersProcessor,
    AuditFiltersProducer,
    EnvSetupRequest,
    EnvSetupRequestConsumer,
    EnvSetupProcessor,
    EnvSetupProducer,
)


def run_auth(args: argparse.Namespace) -> int:
    """Authenticate with Gmail."""
    request = AuthRequest(
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        profile=getattr(args, "profile", None),
        validate=getattr(args, "validate", False),
    )
    envelope = AuthProcessor().process(AuthRequestConsumer(request).consume())
    AuthProducer().produce(envelope)
    if envelope.payload and not envelope.payload.success:
        if getattr(args, "validate", False):
            return 2 if "not found" in envelope.payload.message else 3
        return 1
    return 0


def run_backup(args: argparse.Namespace) -> int:
    """Backup Gmail labels and filters to a timestamped folder."""
    request = BackupRequest(
        out_dir=getattr(args, "out_dir", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        cache=getattr(args, "cache", None),
        profile=getattr(args, "profile", None),
    )
    envelope = BackupProcessor().process(BackupRequestConsumer(request).consume())
    BackupProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_cache_stats(args: argparse.Namespace) -> int:
    """Show cache stats."""
    request = CacheStatsRequest(cache_path=args.cache)
    envelope = CacheStatsProcessor().process(CacheStatsRequestConsumer(request).consume())
    CacheStatsProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_cache_clear(args: argparse.Namespace) -> int:
    """Delete entire cache."""
    request = CacheClearRequest(cache_path=args.cache)
    envelope = CacheClearProcessor().process(CacheClearRequestConsumer(request).consume())
    CacheClearProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_cache_prune(args: argparse.Namespace) -> int:
    """Prune files older than N days from cache."""
    request = CachePruneRequest(cache_path=args.cache, days=int(args.days))
    envelope = CachePruneProcessor().process(CachePruneRequestConsumer(request).consume())
    CachePruneProducer().produce(envelope)
    return 0 if envelope.ok() else 1


def run_config_inspect(args: argparse.Namespace) -> int:
    """Show config with redacted secrets."""
    request = ConfigInspectRequest(
        path=args.path,
        section=getattr(args, "section", None),
        only_mail=getattr(args, "only_mail", False),
    )
    envelope = ConfigInspectProcessor().process(ConfigInspectRequestConsumer(request).consume())
    ConfigInspectProducer().produce(envelope)
    if not envelope.ok():
        msg = (envelope.diagnostics or {}).get("message", "")
        if "not found" in msg:
            return 2
        if "Failed to read" in msg:
            return 3
        if "Section not found" in msg:
            return 4
    return 0 if envelope.ok() else 1


def run_config_derive_labels(args: argparse.Namespace) -> int:
    """Derive Gmail and Outlook labels YAML from unified labels.yaml."""
    request = DeriveLabelsRequest(
        in_path=getattr(args, "in_path", None) or "",
        out_gmail=args.out_gmail,
        out_outlook=args.out_outlook,
    )
    envelope = DeriveLabelsProcessor().process(DeriveLabelsRequestConsumer(request).consume())
    DeriveLabelsProducer().produce(envelope)
    return 0 if envelope.ok() else 2


def run_config_derive_filters(args: argparse.Namespace) -> int:
    """Derive Gmail and Outlook filters YAML from unified filters.yaml."""
    request = DeriveFiltersRequest(
        in_path=getattr(args, "in_path", None) or "",
        out_gmail=args.out_gmail,
        out_outlook=args.out_outlook,
        outlook_archive_on_remove_inbox=getattr(args, "outlook_archive_on_remove_inbox", False),
        outlook_move_to_folders=getattr(args, "outlook_move_to_folders", False),
    )
    envelope = DeriveFiltersProcessor().process(DeriveFiltersRequestConsumer(request).consume())
    DeriveFiltersProducer().produce(envelope)
    return 0 if envelope.ok() else 2


def run_config_optimize_filters(args: argparse.Namespace) -> int:
    """Merge rules with same destination label and simple from criteria."""
    request = OptimizeFiltersRequest(
        in_path=getattr(args, "in_path", None) or "",
        out_path=args.out,
        merge_threshold=int(getattr(args, "merge_threshold", 2) or 2),
        preview=getattr(args, "preview", False),
    )
    envelope = OptimizeFiltersProcessor().process(OptimizeFiltersRequestConsumer(request).consume())
    OptimizeFiltersProducer(preview=request.preview).produce(envelope)
    return 0 if envelope.ok() else 2


def run_config_audit_filters(args: argparse.Namespace) -> int:
    """Report percentage of simple Gmail rules not present in unified config."""
    request = AuditFiltersRequest(
        in_path=getattr(args, "in_path", None) or "",
        export_path=getattr(args, "export_path", None) or "",
        preview_missing=getattr(args, "preview_missing", False),
    )
    envelope = AuditFiltersProcessor().process(AuditFiltersRequestConsumer(request).consume())
    AuditFiltersProducer(preview_missing=request.preview_missing).produce(envelope)
    return 0 if envelope.ok() else 1


def run_workflows_gmail_from_unified(args: argparse.Namespace) -> int:
    """Workflow: derive Gmail filters from unified, plan, and optionally apply."""
    from pathlib import Path
    from ..filters.commands import run_filters_plan, run_filters_sync

    out_dir = Path(getattr(args, 'out_dir', 'out'))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_gmail = out_dir / "filters.gmail.from_unified.yaml"
    out_outlook = out_dir / "filters.outlook.from_unified.yaml"

    # 1) Derive provider-specific configs from unified
    request = DeriveFiltersRequest(
        in_path=args.config,
        out_gmail=str(out_gmail),
        out_outlook=str(out_outlook),
        outlook_move_to_folders=True,
    )
    envelope = DeriveFiltersProcessor().process(DeriveFiltersRequestConsumer(request).consume())
    DeriveFiltersProducer().produce(envelope)
    if not envelope.ok():
        return 2

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
    request = EnvSetupRequest(
        venv_dir=getattr(args, "venv_dir", ".venv") or ".venv",
        no_venv=getattr(args, "no_venv", False),
        skip_install=getattr(args, "skip_install", False),
        profile=getattr(args, "profile", None),
        credentials=getattr(args, "credentials", None),
        token=getattr(args, "token", None),
        outlook_client_id=getattr(args, "outlook_client_id", None),
        tenant=getattr(args, "tenant", None),
        outlook_token=getattr(args, "outlook_token", None),
        copy_gmail_example=getattr(args, "copy_gmail_example", False),
    )
    envelope = EnvSetupProcessor().process(EnvSetupRequestConsumer(request).consume())
    EnvSetupProducer().produce(envelope)
    return 0 if envelope.ok() else 2


def run_workflows_from_unified(args: argparse.Namespace) -> int:
    """Workflow: derive provider configs from unified and plan/apply per provider."""
    import os
    from pathlib import Path
    from ..filters.commands import run_filters_plan, run_filters_sync
    from ..outlook.commands import run_outlook_rules_plan, run_outlook_rules_sync
    from ..outlook.helpers import resolve_outlook_args as _resolve_outlook_args

    out_dir = Path(getattr(args, 'out_dir', 'out'))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_gmail = out_dir / "filters.gmail.from_unified.yaml"
    out_outlook = out_dir / "filters.outlook.from_unified.yaml"

    # 0) Derive both provider configs from unified
    request = DeriveFiltersRequest(
        in_path=args.config,
        out_gmail=str(out_gmail),
        out_outlook=str(out_outlook),
        outlook_move_to_folders=bool(getattr(args, 'outlook_move_to_folders', True)),
    )
    envelope = DeriveFiltersProcessor().process(DeriveFiltersRequestConsumer(request).consume())
    DeriveFiltersProducer().produce(envelope)
    if not envelope.ok():
        return 2

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
