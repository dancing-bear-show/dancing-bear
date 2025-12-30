"""Pipeline primitives for config commands."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pipeline import (
    BaseProducer,
    RequestConsumer,
    SafeProcessor,
)


# -----------------------------------------------------------------------------
# Auth pipeline
# -----------------------------------------------------------------------------


@dataclass
class AuthRequest:
    """Request for authentication."""

    credentials: Optional[str] = None
    token: Optional[str] = None
    profile: Optional[str] = None
    validate: bool = False


@dataclass
class AuthResult:
    """Result from authentication."""

    success: bool
    message: str


# Type alias using generic RequestConsumer from core.pipeline
AuthRequestConsumer = RequestConsumer[AuthRequest]


class AuthProcessor(SafeProcessor[AuthRequest, AuthResult]):
    def _process_safe(self, payload: AuthRequest) -> AuthResult:
        from ..config_resolver import persist_if_provided, resolve_paths_profile

        creds_path, token_path = resolve_paths_profile(
            arg_credentials=payload.credentials,
            arg_token=payload.token,
            profile=payload.profile,
        )

        if payload.validate:
            try:
                from google.auth.transport.requests import Request
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                from ..gmail_api import SCOPES as GMAIL_SCOPES
            except Exception as e:
                raise ValueError(f"Gmail validation unavailable: {e}")
            if not token_path or not os.path.exists(token_path):
                raise ValueError(f"Token file not found: {token_path or '<unspecified>'}")
            try:
                creds = Credentials.from_authorized_user_file(token_path, scopes=GMAIL_SCOPES)
                if creds and creds.expired and getattr(creds, 'refresh_token', None):
                    creds.refresh(Request())
                svc = build("gmail", "v1", credentials=creds)
                _ = svc.users().getProfile(userId="me").execute()
                return AuthResult(success=True, message="Gmail token valid.")
            except Exception as e:
                raise ValueError(f"Gmail token invalid: {e}")

        from ..gmail_api import GmailClient
        client = GmailClient(credentials_path=creds_path, token_path=token_path)
        client.authenticate()
        persist_if_provided(arg_credentials=payload.credentials, arg_token=payload.token)
        return AuthResult(success=True, message="Authentication complete.")


class AuthProducer(BaseProducer):
    def _produce_success(self, payload: AuthResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(payload.message)


# -----------------------------------------------------------------------------
# Backup pipeline
# -----------------------------------------------------------------------------


@dataclass
class BackupRequest:
    """Request for backup."""

    out_dir: Optional[str] = None
    credentials: Optional[str] = None
    token: Optional[str] = None
    cache: Optional[str] = None
    profile: Optional[str] = None


@dataclass
class BackupResult:
    """Result from backup."""

    out_path: str
    labels_count: int
    filters_count: int


# Type alias using generic RequestConsumer from core.pipeline
BackupRequestConsumer = RequestConsumer[BackupRequest]


class BackupProcessor(SafeProcessor[BackupRequest, BackupResult]):
    def _process_safe(self, payload: BackupRequest) -> BackupResult:
        import argparse
        from datetime import datetime
        from ..utils.cli_helpers import gmail_provider_from_args
        from ..yamlio import dump_config

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(payload.out_dir) if payload.out_dir else Path("backups") / ts
        out_dir.mkdir(parents=True, exist_ok=True)

        args = argparse.Namespace(
            credentials=payload.credentials,
            token=payload.token,
            cache=payload.cache,
            profile=payload.profile,
        )
        client = gmail_provider_from_args(args)
        client.authenticate()

        # Labels
        labels = client.list_labels()
        labels_doc = {
            "labels": [
                {k: v for k, v in lab.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
                for lab in labels if lab.get("type") != "system"
            ],
            "redirects": [],
        }
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
                "match": {k: v for k, v in crit.items() if k in ("from", "to", "subject", "query", "negatedQuery", "hasAttachment", "size", "sizeComparison") and v not in (None, "")},
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

        return BackupResult(
            out_path=str(out_dir),
            labels_count=len(labels_doc["labels"]),
            filters_count=len(dsl_filters),
        )


class BackupProducer(BaseProducer):
    def _produce_success(self, payload: BackupResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Backup written to {payload.out_path}")


# -----------------------------------------------------------------------------
# Cache stats pipeline
# -----------------------------------------------------------------------------


@dataclass
class CacheStatsRequest:
    """Request for cache stats."""

    cache_path: str


@dataclass
class CacheStatsResult:
    """Result from cache stats."""

    path: str
    files: int
    size_bytes: int


# Type alias using generic RequestConsumer from core.pipeline
CacheStatsRequestConsumer = RequestConsumer[CacheStatsRequest]


class CacheStatsProcessor(SafeProcessor[CacheStatsRequest, CacheStatsResult]):
    def _process_safe(self, payload: CacheStatsRequest) -> CacheStatsResult:
        root = Path(payload.cache_path)
        total = 0
        files = 0
        for p in root.rglob("*"):
            if p.is_file():
                files += 1
                try:
                    total += p.stat().st_size
                except Exception:  # noqa: S110 - fallback on error
                    pass
        return CacheStatsResult(path=str(root), files=files, size_bytes=total)


class CacheStatsProducer(BaseProducer):
    def _produce_success(self, payload: CacheStatsResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Cache: {payload.path} files={payload.files} size={payload.size_bytes} bytes")


# -----------------------------------------------------------------------------
# Cache clear pipeline
# -----------------------------------------------------------------------------


@dataclass
class CacheClearRequest:
    """Request for cache clear."""

    cache_path: str


@dataclass
class CacheClearResult:
    """Result from cache clear."""

    path: str
    cleared: bool


# Type alias using generic RequestConsumer from core.pipeline
CacheClearRequestConsumer = RequestConsumer[CacheClearRequest]


class CacheClearProcessor(SafeProcessor[CacheClearRequest, CacheClearResult]):
    def _process_safe(self, payload: CacheClearRequest) -> CacheClearResult:
        import shutil

        root = Path(payload.cache_path)
        if not root.exists():
            return CacheClearResult(path=str(root), cleared=False)
        shutil.rmtree(root)
        return CacheClearResult(path=str(root), cleared=True)


class CacheClearProducer(BaseProducer):
    def _produce_success(self, payload: CacheClearResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        if payload.cleared:
            print(f"Cleared cache: {payload.path}")
        else:
            print("Cache does not exist.")


# -----------------------------------------------------------------------------
# Cache prune pipeline
# -----------------------------------------------------------------------------


@dataclass
class CachePruneRequest:
    """Request for cache prune."""

    cache_path: str
    days: int


@dataclass
class CachePruneResult:
    """Result from cache prune."""

    path: str
    removed: int
    days: int


# Type alias using generic RequestConsumer from core.pipeline
CachePruneRequestConsumer = RequestConsumer[CachePruneRequest]


class CachePruneProcessor(SafeProcessor[CachePruneRequest, CachePruneResult]):
    def _process_safe(self, payload: CachePruneRequest) -> CachePruneResult:
        import time

        root = Path(payload.cache_path)
        if not root.exists():
            return CachePruneResult(path=str(root), removed=0, days=payload.days)
        cutoff = time.time() - (payload.days * 86400)
        removed = 0
        for p in root.rglob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except Exception:  # noqa: S110 - fallback on error
                pass
        return CachePruneResult(path=str(root), removed=removed, days=payload.days)


class CachePruneProducer(BaseProducer):
    def _produce_success(self, payload: CachePruneResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Pruned {payload.removed} files older than {payload.days} days from {payload.path}")


# -----------------------------------------------------------------------------
# Config inspect pipeline
# -----------------------------------------------------------------------------


@dataclass
class ConfigInspectRequest:
    """Request for config inspect."""

    path: str
    section: Optional[str] = None
    only_mail: bool = False


@dataclass
class ConfigSection:
    """A config section with masked values."""

    name: str
    items: List[tuple]


@dataclass
class ConfigInspectResult:
    """Result from config inspect."""

    sections: List[ConfigSection]


# Type alias using generic RequestConsumer from core.pipeline
ConfigInspectRequestConsumer = RequestConsumer[ConfigInspectRequest]


class ConfigInspectProcessor(SafeProcessor[ConfigInspectRequest, ConfigInspectResult]):
    def _process_safe(self, payload: ConfigInspectRequest) -> ConfigInspectResult:
        import configparser
        from ..utils.shield import mask_value as _mask_value

        ini = Path(os.path.expanduser(payload.path))
        if not ini.exists():
            raise FileNotFoundError(f"Config not found: {ini}")
        cp = configparser.ConfigParser()
        cp.read(ini)

        sections = cp.sections()
        if payload.section:
            sections = [s for s in sections if s == payload.section]
            if not sections:
                raise ValueError(f"Section not found: {payload.section}")
        elif payload.only_mail:
            sections = [s for s in sections if s.startswith("mail")]

        result_sections = []
        for s in sections:
            [(_mask_value(k, v), k, v) for k, v in cp.items(s)]
            result_sections.append(ConfigSection(
                name=s,
                items=[(k, _mask_value(k, v)) for k, v in cp.items(s)],
            ))

        return ConfigInspectResult(sections=result_sections)


class ConfigInspectProducer(BaseProducer):
    def _produce_success(self, payload: ConfigInspectResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        for section in payload.sections:
            print(f"[{section.name}]")
            for k, v in section.items:
                print(f"{k} = {v}")
            print("")


# -----------------------------------------------------------------------------
# Derive labels pipeline
# -----------------------------------------------------------------------------


@dataclass
class DeriveLabelsRequest:
    """Request for deriving labels."""

    in_path: str
    out_gmail: str
    out_outlook: str


@dataclass
class DeriveLabelsResult:
    """Result from deriving labels."""

    gmail_path: str
    outlook_path: str
    labels_count: int


# Type alias using generic RequestConsumer from core.pipeline
DeriveLabelsRequestConsumer = RequestConsumer[DeriveLabelsRequest]


class DeriveLabelsProcessor(SafeProcessor[DeriveLabelsRequest, DeriveLabelsResult]):
    def _process_safe(self, payload: DeriveLabelsRequest) -> DeriveLabelsResult:
        from ..yamlio import load_config, dump_config
        from ..dsl import normalize_labels_for_outlook

        doc = load_config(payload.in_path) if payload.in_path else {}
        labels = doc.get("labels") or []
        if not isinstance(labels, list):
            raise ValueError("Input missing labels: []")

        # Gmail: pass-through
        out_g = Path(payload.out_gmail)
        out_g.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_g), {"labels": labels})

        # Outlook: normalized names/colors
        out_o = Path(payload.out_outlook)
        out_o.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_o), {"labels": normalize_labels_for_outlook(labels)})

        return DeriveLabelsResult(
            gmail_path=str(out_g),
            outlook_path=str(out_o),
            labels_count=len(labels),
        )


class DeriveLabelsProducer(BaseProducer):
    def _produce_success(self, payload: DeriveLabelsResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Derived labels -> gmail:{payload.gmail_path} outlook:{payload.outlook_path}")


# -----------------------------------------------------------------------------
# Derive filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class DeriveFiltersRequest:
    """Request for deriving filters."""

    in_path: str
    out_gmail: str
    out_outlook: str
    outlook_archive_on_remove_inbox: bool = False
    outlook_move_to_folders: bool = False


@dataclass
class DeriveFiltersResult:
    """Result from deriving filters."""

    gmail_path: str
    outlook_path: str
    filters_count: int


# Type alias using generic RequestConsumer from core.pipeline
DeriveFiltersRequestConsumer = RequestConsumer[DeriveFiltersRequest]


class DeriveFiltersProcessor(SafeProcessor[DeriveFiltersRequest, DeriveFiltersResult]):
    def _process_safe(self, payload: DeriveFiltersRequest) -> DeriveFiltersResult:
        from ..yamlio import load_config, dump_config
        from ..dsl import normalize_filters_for_outlook

        doc = load_config(payload.in_path) if payload.in_path else {}
        filters = doc.get("filters") or []
        if not isinstance(filters, list):
            raise ValueError("Input missing filters: []")

        # Gmail: pass-through
        out_g = Path(payload.out_gmail)
        out_g.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_g), {"filters": filters})

        # Outlook: normalized subset
        out_specs = normalize_filters_for_outlook(filters)
        if payload.outlook_archive_on_remove_inbox:
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
        elif payload.outlook_move_to_folders:
            for spec in out_specs:
                a = spec.get("action") or {}
                adds = a.get("add") or []
                if adds and not a.get("moveToFolder"):
                    a["moveToFolder"] = str(adds[0])
                    spec["action"] = a

        out_o = Path(payload.out_outlook)
        out_o.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(out_o), {"filters": out_specs})

        return DeriveFiltersResult(
            gmail_path=str(out_g),
            outlook_path=str(out_o),
            filters_count=len(filters),
        )


class DeriveFiltersProducer(BaseProducer):
    def _produce_success(self, payload: DeriveFiltersResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Derived filters -> gmail:{payload.gmail_path} outlook:{payload.outlook_path}")


# -----------------------------------------------------------------------------
# Optimize filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class OptimizeFiltersRequest:
    """Request for optimizing filters."""

    in_path: str
    out_path: str
    merge_threshold: int = 2
    preview: bool = False


@dataclass
class MergedGroup:
    """Info about a merged group."""

    destination: str
    rules_merged: int
    unique_from_terms: int


@dataclass
class OptimizeFiltersResult:
    """Result from optimizing filters."""

    out_path: str
    original_count: int
    optimized_count: int
    merged_groups: List[MergedGroup]


# Type alias using generic RequestConsumer from core.pipeline
OptimizeFiltersRequestConsumer = RequestConsumer[OptimizeFiltersRequest]


class OptimizeFiltersProcessor(SafeProcessor[OptimizeFiltersRequest, OptimizeFiltersResult]):
    def _process_safe(self, payload: OptimizeFiltersRequest) -> OptimizeFiltersResult:
        from collections import defaultdict
        from ..yamlio import load_config, dump_config

        doc = load_config(payload.in_path) if payload.in_path else {}
        rules = doc.get("filters") or []
        if not isinstance(rules, list):
            raise ValueError("Input missing filters: []")

        groups: Dict[str, list] = defaultdict(list)
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
        preview_info = []
        threshold = max(2, payload.merge_threshold)
        for dest, items in groups.items():
            if len(items) < threshold:
                passthrough.extend(items)
                continue
            terms = []
            removes: set = set()
            for it in items:
                m = it.get('match') or {}
                a = it.get('action') or {}
                frm = str(m.get('from') or '').strip()
                if frm:
                    terms.append(frm)
                for x in a.get('remove') or []:
                    removes.add(x)
            atoms = []
            for t in terms:
                parts = [p.strip() for p in t.split('OR') if p.strip()]
                atoms.extend(parts)
            uniq = sorted({a for a in atoms})
            if not uniq:
                passthrough.extend(items)
                continue
            merged_rule = {
                'name': f'merged_{dest.replace("/", "_")}',
                'match': {'from': ' OR '.join(uniq)},
                'action': {'add': [dest]},
            }
            if removes:
                merged_rule['action']['remove'] = sorted(removes)
            merged.append(merged_rule)
            preview_info.append(MergedGroup(destination=dest, rules_merged=len(items), unique_from_terms=len(uniq)))

        optimized = {'filters': merged + passthrough}
        outp = Path(payload.out_path)
        outp.parent.mkdir(parents=True, exist_ok=True)
        dump_config(str(outp), optimized)

        return OptimizeFiltersResult(
            out_path=str(outp),
            original_count=len(rules),
            optimized_count=len(optimized['filters']),
            merged_groups=preview_info,
        )


class OptimizeFiltersProducer(BaseProducer):
    def __init__(self, preview: bool = False) -> None:
        self._preview = preview

    def _produce_success(self, payload: OptimizeFiltersResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        if self._preview and payload.merged_groups:
            print('Merged groups:')
            for g in sorted(payload.merged_groups, key=lambda x: -x.rules_merged):
                print(f'- {g.destination}: merged {g.rules_merged} rules into 1 (unique from terms={g.unique_from_terms})')
        print(f"Optimized filters written to {payload.out_path}. Original={payload.original_count} Optimized={payload.optimized_count}")


# -----------------------------------------------------------------------------
# Audit filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class AuditFiltersRequest:
    """Request for auditing filters."""

    in_path: str
    export_path: str
    preview_missing: bool = False


@dataclass
class AuditFiltersResult:
    """Result from auditing filters."""

    simple_total: int
    covered: int
    not_covered: int
    percentage: float
    missing_samples: List[tuple]


# Type alias using generic RequestConsumer from core.pipeline
AuditFiltersRequestConsumer = RequestConsumer[AuditFiltersRequest]


class AuditFiltersProcessor(SafeProcessor[AuditFiltersRequest, AuditFiltersResult]):
    def _process_safe(self, payload: AuditFiltersRequest) -> AuditFiltersResult:
        from ..yamlio import load_config

        uni = load_config(payload.in_path) if payload.in_path else {}
        exp = load_config(payload.export_path) if payload.export_path else {}
        unified = uni.get('filters') or []
        exported = exp.get('filters') or []

        dest_to_from_tokens: Dict[str, set] = {}
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
        missing_samples: List[tuple] = []
        for f in exported:
            if not isinstance(f, dict):
                continue
            c = f.get('criteria') or f.get('match') or {}
            a = f.get('action') or {}
            if any(k in c for k in ('query', 'negatedQuery', 'size', 'sizeComparison')):
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

        return AuditFiltersResult(
            simple_total=simple_total,
            covered=covered,
            not_covered=not_cov,
            percentage=pct,
            missing_samples=missing_samples,
        )


class AuditFiltersProducer(BaseProducer):
    def __init__(self, preview_missing: bool = False) -> None:
        self._preview_missing = preview_missing

    def _produce_success(self, payload: AuditFiltersResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(f"Simple Gmail rules: {payload.simple_total}")
        print(f"Covered by unified: {payload.covered}")
        print(f"Not unified: {payload.not_covered} ({payload.percentage:.1f}%)")
        if self._preview_missing and payload.missing_samples:
            print("Missing examples (dest, from):")
            for dest, frm in payload.missing_samples:
                print(f"- {dest} <- {frm}")


# -----------------------------------------------------------------------------
# Env setup pipeline
# -----------------------------------------------------------------------------


@dataclass
class EnvSetupRequest:
    """Request for environment setup."""

    venv_dir: str = ".venv"
    no_venv: bool = False
    skip_install: bool = False
    profile: Optional[str] = None
    credentials: Optional[str] = None
    token: Optional[str] = None
    outlook_client_id: Optional[str] = None
    tenant: Optional[str] = None
    outlook_token: Optional[str] = None
    copy_gmail_example: bool = False


@dataclass
class EnvSetupResult:
    """Result from environment setup."""

    venv_created: bool
    profile_saved: bool
    message: str


# Type alias using generic RequestConsumer from core.pipeline
EnvSetupRequestConsumer = RequestConsumer[EnvSetupRequest]


class EnvSetupProcessor(SafeProcessor[EnvSetupRequest, EnvSetupResult]):
    def _process_safe(self, payload: EnvSetupRequest) -> EnvSetupResult:
        from ..config_resolver import (
            default_gmail_credentials_path,
            default_gmail_token_path,
            expand_path,
            persist_profile_settings,
        )

        venv_created = False
        profile_saved = False

        venv_dir = Path(payload.venv_dir)
        if not payload.no_venv:
            if not venv_dir.exists():
                import venv
                venv.EnvBuilder(with_pip=True).create(str(venv_dir))
                venv_created = True
            if not payload.skip_install:
                import subprocess
                py = venv_dir / 'bin' / 'python'
                subprocess.run([str(py), '-m', 'pip', 'install', '-U', 'pip'], check=True, capture_output=True)  # noqa: S603
                subprocess.run([str(py), '-m', 'pip', 'install', '-e', '.'], check=True, capture_output=True)  # noqa: S603
            for fname in ('bin/mail', 'bin/mail-assistant'):
                try:
                    p = Path(fname)
                    if p.exists():
                        os.chmod(p, (p.stat().st_mode | 0o111))
                except Exception:  # noqa: S110 - fallback on error
                    pass

        cred_path = payload.credentials
        tok_path = payload.token

        if payload.copy_gmail_example and not cred_path:
            ex = Path('credentials.example.json')
            dest = Path(expand_path(default_gmail_credentials_path()))
            if ex.exists() and not dest.exists():
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(ex.read_text(encoding='utf-8'), encoding='utf-8')
                    cred_path = str(dest)
                except Exception:  # noqa: S110 - fallback on error
                    pass
        if cred_path and not tok_path:
            tok_path = default_gmail_token_path()

        for pth in (cred_path, tok_path, payload.outlook_token):
            if pth:
                try:
                    Path(os.path.expanduser(pth)).parent.mkdir(parents=True, exist_ok=True)
                except Exception:  # noqa: S110 - fallback on error
                    pass

        if any([cred_path, tok_path, payload.outlook_client_id, payload.tenant, payload.outlook_token]):
            persist_profile_settings(
                profile=payload.profile,
                credentials=cred_path,
                token=tok_path,
                outlook_client_id=payload.outlook_client_id,
                tenant=payload.tenant,
                outlook_token=payload.outlook_token,
            )
            profile_saved = True

        return EnvSetupResult(
            venv_created=venv_created,
            profile_saved=profile_saved,
            message="Environment setup complete.",
        )


class EnvSetupProducer(BaseProducer):
    def _produce_success(self, payload: EnvSetupResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        if payload.profile_saved:
            print("Persisted settings to ~/.config/credentials.ini")
        else:
            print("No profile settings provided; skipped INI write.")
        print(payload.message)
