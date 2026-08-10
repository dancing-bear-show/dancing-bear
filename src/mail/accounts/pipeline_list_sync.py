"""Sync labels and filters pipeline implementations for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.pipeline import SafeProcessor

from .pipeline_auth import (
    AccountsResultProducer,
    SimpleConsumer,
    _sync_outlook_filters,
    _sync_labels_for_account,
)


@dataclass
class AccountsSyncLabelsRequest:
    """Request for syncing labels to accounts."""

    config_path: str
    labels_path: str
    accounts_filter: list[str] | None = None
    dry_run: bool = False


@dataclass
class SyncedLabelInfo:
    """Info about synced labels for one account."""

    account_name: str
    provider: str
    created: int
    updated: int


@dataclass
class AccountsSyncLabelsResult:
    """Result from syncing labels."""

    synced: list[SyncedLabelInfo] = field(default_factory=list)


AccountsSyncLabelsRequestConsumer = SimpleConsumer[AccountsSyncLabelsRequest]


class AccountsSyncLabelsProcessor(SafeProcessor[AccountsSyncLabelsRequest, AccountsSyncLabelsResult]):
    def _process_safe(self, payload: AccountsSyncLabelsRequest) -> AccountsSyncLabelsResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_labels_for_outlook

        accts = load_accounts(payload.config_path)
        desired_doc = load_config(payload.labels_path)
        desired_base = desired_doc.get("labels") or []

        synced: list[SyncedLabelInfo] = []
        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()
            client = build_provider_for_account(a)
            client.authenticate()
            desired = normalize_labels_for_outlook(desired_base) if provider == "outlook" else desired_base
            existing = {lab.get("name", ""): lab for lab in client.list_labels()}

            created, updated = _sync_labels_for_account(client, desired, existing, provider, payload.dry_run)

            synced.append(SyncedLabelInfo(
                account_name=a.get("name", "account"),
                provider=provider,
                created=created,
                updated=updated,
            ))

        return AccountsSyncLabelsResult(synced=synced)


class AccountsSyncLabelsProducer(AccountsResultProducer[AccountsSyncLabelsResult]):
    def _produce_items(self, payload: AccountsSyncLabelsResult) -> None:
        verb = "would" if self._dry_run else ""
        for info in payload.synced:
            print(f"[labels sync] {info.account_name} provider={info.provider} {verb} created={info.created} updated={info.updated}")


# -----------------------------------------------------------------------------
# Plan filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class AccountsSyncFiltersRequest:
    """Request for syncing filters to accounts."""

    config_path: str
    filters_path: str
    accounts_filter: list[str] | None = None
    dry_run: bool = False
    require_forward_verified: bool = False


@dataclass
class SyncedFiltersInfo:
    """Info about synced filters for one account."""

    account_name: str
    provider: str
    created: int
    errors: int


@dataclass
class AccountsSyncFiltersResult:
    """Result from syncing filters."""

    synced: list[SyncedFiltersInfo] = field(default_factory=list)


AccountsSyncFiltersRequestConsumer = SimpleConsumer[AccountsSyncFiltersRequest]


def _sync_filters_gmail(a: dict, payload: "AccountsSyncFiltersRequest") -> SyncedFiltersInfo:
    """Delegate Gmail filter sync to run_filters_sync."""
    import argparse
    from ..filters.commands import run_filters_sync

    ns = argparse.Namespace(
        credentials=a.get("credentials"),
        token=a.get("token"),
        cache=a.get("cache"),
        config=payload.filters_path,
        dry_run=payload.dry_run,
        delete_missing=False,
        require_forward_verified=payload.require_forward_verified,
    )
    run_filters_sync(ns)
    return SyncedFiltersInfo(
        account_name=a.get("name", "account"),
        provider="gmail",
        created=-1,  # delegated to run_filters_sync
        errors=0,
    )


def _sync_filters_outlook(a: dict, payload: "AccountsSyncFiltersRequest") -> SyncedFiltersInfo:
    """Sync Outlook filters directly against the Graph API."""
    from .helpers import build_client_for_account
    from ..yamlio import load_config
    from ..dsl import normalize_filters_for_outlook

    client = build_client_for_account(a)
    client.authenticate()
    doc = load_config(payload.filters_path)
    desired = normalize_filters_for_outlook(doc.get("filters") or [])
    existing = client.list_filters()
    name_to_id = client.get_label_id_map()

    created, errors = _sync_outlook_filters(client, desired, existing, name_to_id, payload.dry_run)
    return SyncedFiltersInfo(
        account_name=a.get("name", "account"),
        provider="outlook",
        created=created,
        errors=errors,
    )


def _sync_filters_unsupported(a: dict, provider: str) -> SyncedFiltersInfo:
    """Record an unsupported-provider result without attempting sync."""
    return SyncedFiltersInfo(
        account_name=a.get("name", "account"),
        provider=provider,
        created=-1,
        errors=0,
    )


# provider -> sync function; bound as functions, not calls (evaluated at import time)
_FILTERS_SYNC_BY_PROVIDER = {
    "gmail": _sync_filters_gmail,
    "outlook": _sync_filters_outlook,
}


class AccountsSyncFiltersProcessor(SafeProcessor[AccountsSyncFiltersRequest, AccountsSyncFiltersResult]):
    def _process_safe(self, payload: AccountsSyncFiltersRequest) -> AccountsSyncFiltersResult:
        from .helpers import load_accounts, iter_accounts

        accts = load_accounts(payload.config_path)
        synced: list[SyncedFiltersInfo] = []

        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()
            sync_fn = _FILTERS_SYNC_BY_PROVIDER.get(provider)
            if sync_fn is None:
                synced.append(_sync_filters_unsupported(a, provider))
            else:
                synced.append(sync_fn(a, payload))

        return AccountsSyncFiltersResult(synced=synced)


class AccountsSyncFiltersProducer(AccountsResultProducer[AccountsSyncFiltersResult]):
    def _produce_items(self, payload: AccountsSyncFiltersResult) -> None:
        verb = "would" if self._dry_run else ""
        for info in payload.synced:
            if info.created < 0:
                print(f"[filters sync] {info.account_name} provider={info.provider} (delegated)")
            else:
                print(f"[filters sync] {info.account_name} provider={info.provider} {verb} created={info.created} errors={info.errors}")


# -----------------------------------------------------------------------------
# Export signatures pipeline
# -----------------------------------------------------------------------------
