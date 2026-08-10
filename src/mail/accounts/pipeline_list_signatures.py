"""Export and sync signatures pipeline implementations for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.pipeline import SafeProcessor

from .pipeline_auth import (
    AccountsResultProducer,
    SimpleConsumer,
    _LOG_PREFIX,
)


@dataclass
class AccountsExportSignaturesRequest:
    """Request for exporting signatures from accounts."""

    config_path: str
    out_dir: str
    accounts_filter: list[str] | None = None


@dataclass
class ExportedSignaturesInfo:
    """Info about exported signatures for one account."""

    account_name: str
    provider: str
    output_path: str
    signature_count: int


@dataclass
class AccountsExportSignaturesResult:
    """Result from exporting signatures."""

    exports: list[ExportedSignaturesInfo] = field(default_factory=list)


AccountsExportSignaturesRequestConsumer = SimpleConsumer[AccountsExportSignaturesRequest]


def _export_signatures_gmail(a: dict, doc: dict, assets: Path) -> int:
    """Populate doc['signatures']['gmail'] and write the default iOS signature asset.

    Returns the exported signature count.
    """
    from .helpers import build_provider_for_account

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
    return len(doc["signatures"]["gmail"])


def _export_signatures_outlook(assets: Path) -> int:
    """Write guidance for Outlook, which has no signature export API. Returns 0."""
    (assets / "OUTLOOK_README.txt").write_text(
        "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
        "Use ios_signature.html exported from a Gmail account, or paste HTML manually.",
        encoding="utf-8",
    )
    return 0


def _export_signatures_for_account(a: dict, out_dir: Path) -> ExportedSignaturesInfo:
    """Export signatures (or write provider guidance) for a single account."""
    from ..yamlio import dump_config

    name = a.get("name", "account")
    provider = (a.get("provider") or "").lower()
    path = out_dir / f"signatures_{name}.yaml"
    assets = out_dir / f"{name}_assets"
    assets.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {"signatures": {"gmail": [], "ios": {}, "outlook": []}}

    if provider == "gmail":
        sig_count = _export_signatures_gmail(a, doc, assets)
    elif provider == "outlook":
        sig_count = _export_signatures_outlook(assets)
    else:
        sig_count = 0

    dump_config(str(path), doc)
    return ExportedSignaturesInfo(
        account_name=name,
        provider=provider,
        output_path=str(path),
        signature_count=sig_count,
    )


class AccountsExportSignaturesProcessor(SafeProcessor[AccountsExportSignaturesRequest, AccountsExportSignaturesResult]):
    def _process_safe(self, payload: AccountsExportSignaturesRequest) -> AccountsExportSignaturesResult:
        from .helpers import load_accounts, iter_accounts

        accts = load_accounts(payload.config_path)
        out_dir = Path(payload.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exports = [
            _export_signatures_for_account(a, out_dir)
            for a in iter_accounts(accts, payload.accounts_filter)
        ]
        return AccountsExportSignaturesResult(exports=exports)


class AccountsExportSignaturesProducer(AccountsResultProducer[AccountsExportSignaturesResult]):
    def _produce_items(self, payload: AccountsExportSignaturesResult) -> None:
        for exp in payload.exports:
            print(f"Exported signatures for {exp.account_name}: {exp.output_path}")


# -----------------------------------------------------------------------------
# Sync signatures pipeline
# -----------------------------------------------------------------------------


@dataclass
class AccountsSyncSignaturesRequest:
    """Request for syncing signatures to accounts."""

    config_path: str
    accounts_filter: list[str] | None = None
    send_as: str | None = None
    dry_run: bool = False


@dataclass
class SyncedSignaturesInfo:
    """Info about synced signatures for one account."""

    account_name: str
    provider: str
    status: str


@dataclass
class AccountsSyncSignaturesResult:
    """Result from syncing signatures."""

    synced: list[SyncedSignaturesInfo] = field(default_factory=list)


AccountsSyncSignaturesRequestConsumer = SimpleConsumer[AccountsSyncSignaturesRequest]


def _sync_signatures_gmail(a: dict, payload: "AccountsSyncSignaturesRequest") -> SyncedSignaturesInfo:
    """Delegate Gmail signature sync to run_signatures_sync."""
    import argparse
    from ..signatures.commands import run_signatures_sync

    ns = argparse.Namespace(
        credentials=a.get("credentials"),
        token=a.get("token"),
        config=payload.config_path,
        send_as=payload.send_as,
        dry_run=payload.dry_run,
        account_display_name=a.get("display_name"),
    )
    run_signatures_sync(ns)
    return SyncedSignaturesInfo(account_name=a.get("name", "account"), provider="gmail", status="delegated")


def _sync_signatures_outlook(a: dict) -> SyncedSignaturesInfo:
    """Write guidance for Outlook, which has no signature sync API."""
    assets = Path("signatures_assets")
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "OUTLOOK_README.txt").write_text(
        "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
        "Use ios_signature.html or paste HTML manually.",
        encoding="utf-8",
    )
    return SyncedSignaturesInfo(account_name=a.get("name", "account"), provider="outlook", status="wrote_guidance")


class AccountsSyncSignaturesProcessor(SafeProcessor[AccountsSyncSignaturesRequest, AccountsSyncSignaturesResult]):
    def _process_safe(self, payload: AccountsSyncSignaturesRequest) -> AccountsSyncSignaturesResult:
        from .helpers import load_accounts, iter_accounts

        accts = load_accounts(payload.config_path)
        synced: list[SyncedSignaturesInfo] = []

        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()

            if provider == "gmail":
                synced.append(_sync_signatures_gmail(a, payload))
            elif provider == "outlook":
                synced.append(_sync_signatures_outlook(a))
            else:
                synced.append(SyncedSignaturesInfo(account_name=a.get("name", "account"), provider=provider, status="unsupported"))

        return AccountsSyncSignaturesResult(synced=synced)


class AccountsSyncSignaturesProducer(AccountsResultProducer[AccountsSyncSignaturesResult]):
    def _produce_items(self, payload: AccountsSyncSignaturesResult) -> None:
        for info in payload.synced:
            if info.status == "delegated":
                print(f"{_LOG_PREFIX}{info.account_name} provider={info.provider} (delegated)")
            elif info.status == "wrote_guidance":
                print(f"{_LOG_PREFIX}{info.account_name} provider={info.provider} wrote guidance to signatures_assets/")
            else:
                print(f"{_LOG_PREFIX}{info.account_name} provider={info.provider} status={info.status}")
