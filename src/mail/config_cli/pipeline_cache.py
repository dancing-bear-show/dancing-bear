"""Pipeline primitives for auth, backup, and cache config commands."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    credentials: str | None = None
    token: str | None = None
    profile: str | None = None
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
            return self._validate_gmail_token(token_path)

        from ..gmail_api import GmailClient
        client = GmailClient(credentials_path=creds_path, token_path=token_path)
        # The one entrypoint whose entire purpose is to (re-)consent, so it is
        # the only caller permitted to open a browser for a stale-scope token.
        client.authenticate(allow_interactive=True)
        persist_if_provided(arg_credentials=payload.credentials, arg_token=payload.token)
        return AuthResult(success=True, message="Authentication complete.")

    def _validate_gmail_token(self, token_path: str | None) -> AuthResult:
        """Validate an existing Gmail token by round-tripping a profile call."""
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


class AuthProducer(BaseProducer):
    def _produce_success(self, payload: AuthResult, diagnostics: dict[str, Any] | None) -> None:
        print(payload.message)


# -----------------------------------------------------------------------------
# Backup pipeline
# -----------------------------------------------------------------------------


@dataclass
class BackupRequest:
    """Request for backup."""

    out_dir: str | None = None
    credentials: str | None = None
    token: str | None = None
    cache: str | None = None
    profile: str | None = None


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
        from core.yamlio import dump_config
        from ..accounts.pipeline_auth import (
            _build_label_id_to_name_map,
            _build_filter_dsl_entry,
        )

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
        id_to_name = _build_label_id_to_name_map(labels)
        filters = client.list_filters()
        dsl_filters = [_build_filter_dsl_entry(f, id_to_name) for f in filters]
        dump_config(str(out_dir / "filters.yaml"), {"filters": dsl_filters})

        return BackupResult(
            out_path=str(out_dir),
            labels_count=len(labels_doc["labels"]),
            filters_count=len(dsl_filters),
        )


class BackupProducer(BaseProducer):
    def _produce_success(self, payload: BackupResult, diagnostics: dict[str, Any] | None) -> None:
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
                except OSError:  # nosec B110 - skip inaccessible/deleted files
                    pass
        return CacheStatsResult(path=str(root), files=files, size_bytes=total)


class CacheStatsProducer(BaseProducer):
    def _produce_success(self, payload: CacheStatsResult, diagnostics: dict[str, Any] | None) -> None:
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
    def _produce_success(self, payload: CacheClearResult, diagnostics: dict[str, Any] | None) -> None:
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
            except OSError:  # nosec B110 - skip deletion failures (FileNotFoundError/PermissionError subclasses)
                pass
        return CachePruneResult(path=str(root), removed=removed, days=payload.days)


class CachePruneProducer(BaseProducer):
    def _produce_success(self, payload: CachePruneResult, diagnostics: dict[str, Any] | None) -> None:
        print(f"Pruned {payload.removed} files older than {payload.days} days from {payload.path}")


# -----------------------------------------------------------------------------
# Config inspect pipeline
# -----------------------------------------------------------------------------


@dataclass
class ConfigInspectRequest:
    """Request for config inspect."""

    path: str
    section: str | None = None
    only_mail: bool = False


@dataclass
class ConfigSection:
    """A config section with masked values."""

    name: str
    items: list[tuple]


@dataclass
class ConfigInspectResult:
    """Result from config inspect."""

    sections: list[ConfigSection]


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
            result_sections.append(ConfigSection(
                name=s,
                items=[(k, _mask_value(k, v)) for k, v in cp.items(s)],
            ))

        return ConfigInspectResult(sections=result_sections)


class ConfigInspectProducer(BaseProducer):
    def _produce_success(self, payload: ConfigInspectResult, diagnostics: dict[str, Any] | None) -> None:
        for section in payload.sections:
            print(f"[{section.name}]")
            for k, v in section.items:
                print(f"{k} = {v}")
            print("")
