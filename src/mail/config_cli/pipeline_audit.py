"""Pipeline primitives for audit and env-setup config commands."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.cli_output import OutputWriter
from core.pipeline import (
    BaseProducer,
    RequestConsumer,
    SafeProcessor,
)


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
    missing_samples: list[tuple]


# Type alias using generic RequestConsumer from core.pipeline
AuditFiltersRequestConsumer = RequestConsumer[AuditFiltersRequest]


def _dest_and_tokens_for_filter(f: dict) -> tuple[str, set] | None:
    """Extract (destination, from-tokens) for a single unified filter, or None if not applicable."""
    if not isinstance(f, dict):
        return None
    adds = (f.get("action") or {}).get("add") or []
    if not adds:
        return None
    frm = str((f.get("match") or {}).get("from") or "")
    toks = {t.strip().lower() for t in frm.split("OR") if t.strip()}
    if not toks:
        return None
    return str(adds[0]), toks


def _build_dest_token_map(unified: list) -> dict[str, set]:
    """Build mapping from destination label to set of from-tokens in the unified config."""
    dest_to_tokens: dict[str, set] = {}
    for f in unified:
        pair = _dest_and_tokens_for_filter(f)
        if pair is None:
            continue
        dest, toks = pair
        dest_to_tokens.setdefault(dest, set()).update(toks)
    return dest_to_tokens


def _extract_filter_from_addr(f: dict) -> str | None:
    """Extract the normalized from-address from a filter entry, or None if not applicable."""
    c = f.get("criteria") or f.get("match") or {}
    if any(k in c for k in ("query", "negatedQuery", "size", "sizeComparison")):
        return None
    if c.get("to") or c.get("subject"):
        return None
    return str(c.get("from") or "").strip().lower() or None


def _extract_filter_adds(f: dict) -> list[str]:
    """Extract the add-labels/folder destinations from a filter action."""
    a = f.get("action") or {}
    adds = a.get("addLabels") or a.get("add") or []
    if not adds and a.get("moveToFolder"):
        adds = [str(a.get("moveToFolder"))]
    return adds


def _token_matches(frm: str, toks: set) -> bool:
    """Return True if any token in toks overlaps with frm."""
    return any(tok and (tok in frm or frm in tok) for tok in toks)


@dataclass(frozen=True)
class _FilterScore:
    """Coverage classification for a single simple filter."""
    dest: str
    frm: str
    covered: bool


def _score_one_filter(f: dict, dest_to_tokens: dict[str, set]) -> "_FilterScore | None":
    """Score a single exported filter, or None if it is not a 'simple' from-based rule."""
    if not isinstance(f, dict):
        return None
    frm = _extract_filter_from_addr(f)
    if frm is None:
        return None
    adds = _extract_filter_adds(f)
    if not adds:
        return None
    dest = str(adds[0])
    toks = dest_to_tokens.get(dest) or set()
    return _FilterScore(dest=dest, frm=frm, covered=_token_matches(frm, toks))


def _score_exported_filters(exported: list, dest_to_tokens: dict[str, set]) -> tuple:
    """Return (simple_total, covered, missing_samples) for exported filters vs unified token map."""
    scores = [s for f in exported if (s := _score_one_filter(f, dest_to_tokens)) is not None]
    simple_total = len(scores)
    covered = sum(1 for s in scores if s.covered)
    missing_samples = [(s.dest, s.frm) for s in scores if not s.covered][:10]
    return simple_total, covered, missing_samples


class AuditFiltersProcessor(SafeProcessor[AuditFiltersRequest, AuditFiltersResult]):
    def _process_safe(self, payload: AuditFiltersRequest) -> AuditFiltersResult:
        from core.yamlio import load_config

        unified = (load_config(payload.in_path) if payload.in_path else {}).get("filters") or []
        exported = (load_config(payload.export_path) if payload.export_path else {}).get("filters") or []

        dest_to_tokens = _build_dest_token_map(unified)
        simple_total, covered, missing_samples = _score_exported_filters(exported, dest_to_tokens)

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
    def __init__(self, preview_missing: bool = False, writer: OutputWriter | None = None) -> None:
        super().__init__(writer)
        self._preview_missing = preview_missing

    def _produce_success(self, payload: AuditFiltersResult, diagnostics: dict[str, Any] | None) -> None:
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
    profile: str | None = None
    credentials: str | None = None
    token: str | None = None
    outlook_client_id: str | None = None
    tenant: str | None = None
    outlook_token: str | None = None
    copy_gmail_example: bool = False


@dataclass
class EnvSetupResult:
    """Result from environment setup."""

    venv_created: bool
    profile_saved: bool
    message: str


# Type alias using generic RequestConsumer from core.pipeline
EnvSetupRequestConsumer = RequestConsumer[EnvSetupRequest]


def _install_venv_packages(venv_dir: Path) -> None:
    """Validate the venv's python path and install pip + this project into it."""
    import subprocess  # nosec B404 - needed for pip install in venv setup

    py = venv_dir / "bin" / "python"
    if not py.exists():
        raise FileNotFoundError(f"Python not found in venv: {py}")
    if venv_dir.resolve() not in py.resolve().parents:
        raise ValueError(f"Python path escapes venv directory: {py}")
    subprocess.run([str(py), "-m", "pip", "install", "-U", "pip"], check=True, capture_output=True)  # nosec B603 - validated path within venv
    subprocess.run([str(py), "-m", "pip", "install", "-e", "."], check=True, capture_output=True)  # nosec B603 - validated path within venv


def _make_bin_scripts_executable() -> None:
    """Best-effort chmod +x on the known bin/ entry scripts."""
    for fname in ("bin/mail", "bin/mail-assistant"):
        try:
            p = Path(fname)
            if p.exists():
                os.chmod(p, (p.stat().st_mode | 0o111))
        except OSError:  # nosec B110 - chmod failure is non-critical (PermissionError is subclass)
            pass


def _setup_venv(venv_dir: Path, skip_install: bool) -> bool:
    """Create and optionally populate a venv. Returns True if created."""
    venv_created = False
    if not venv_dir.exists():
        import venv as _venv
        _venv.EnvBuilder(with_pip=True).create(str(venv_dir))
        venv_created = True
    if not skip_install:
        _install_venv_packages(venv_dir)
    _make_bin_scripts_executable()
    return venv_created


def _resolve_gmail_cred_paths(payload: Any, expand_path, default_cred_fn, default_tok_fn) -> tuple:
    """Resolve credential/token paths, optionally copying the example credentials file."""
    import sys
    cred_path = payload.credentials
    tok_path = payload.token
    if payload.copy_gmail_example and not cred_path:
        ex = Path("credentials.example.json")
        dest = Path(expand_path(default_cred_fn()))
        if ex.exists() and not dest.exists():
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(ex.read_text(encoding="utf-8"), encoding="utf-8")
                cred_path = str(dest)
            except OSError:  # nosec B110 - non-critical setup step (PermissionError/IOError are subclasses)
                print(f"Warning: Could not copy example credentials to {dest}", file=sys.stderr)
    if cred_path and not tok_path:
        tok_path = default_tok_fn()
    return cred_path, tok_path


class EnvSetupProcessor(SafeProcessor[EnvSetupRequest, EnvSetupResult]):
    def _process_safe(self, payload: EnvSetupRequest) -> EnvSetupResult:
        from ..config_resolver import (
            default_gmail_credentials_path,
            default_gmail_token_path,
            expand_path,
            persist_profile_settings,
        )

        venv_created = False
        if not payload.no_venv:
            venv_created = _setup_venv(Path(payload.venv_dir), payload.skip_install)

        cred_path, tok_path = _resolve_gmail_cred_paths(
            payload, expand_path, default_gmail_credentials_path, default_gmail_token_path
        )

        for pth in (cred_path, tok_path, payload.outlook_token):
            if pth:
                try:
                    Path(os.path.expanduser(pth)).parent.mkdir(parents=True, exist_ok=True)
                except OSError:  # nosec B110 - non-critical directory creation
                    pass

        profile_saved = False
        if any([cred_path, tok_path, payload.outlook_client_id, payload.tenant, payload.outlook_token]):
            from mail.config_resolver import ProfileSettings
            persist_profile_settings(ProfileSettings(
                profile=payload.profile,
                credentials=cred_path,
                token=tok_path,
                outlook_client_id=payload.outlook_client_id,
                tenant=payload.tenant,
                outlook_token=payload.outlook_token,
            ))
            profile_saved = True

        return EnvSetupResult(
            venv_created=venv_created,
            profile_saved=profile_saved,
            message="Environment setup complete.",
        )


class EnvSetupProducer(BaseProducer):
    def _produce_success(self, payload: EnvSetupResult, diagnostics: dict[str, Any] | None) -> None:
        if payload.profile_saved:
            print("Persisted settings to ~/.config/credentials.ini")
        else:
            print("No profile settings provided; skipped INI write.")
        print(payload.message)
