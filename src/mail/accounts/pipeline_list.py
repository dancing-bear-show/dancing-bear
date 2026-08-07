"""List, export, plan, and sync pipeline implementations for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.pipeline import SafeProcessor

from .pipeline_auth import (
    AccountAuthenticator,
    AccountsResultProducer,
    SimpleConsumer,
    _build_label_id_to_name_map,
    _build_filter_dsl_entry,
    _needs_label_update,
    _sync_outlook_filters,
    _sync_labels_for_account,
    canonicalize_filter,
    _LOG_PREFIX,
)


_DEFAULT_ACCOUNT_NAME = "account"

# -----------------------------------------------------------------------------
# List accounts pipeline
# -----------------------------------------------------------------------------


@dataclass
class AccountsListRequest:
    """Request for listing accounts."""

    config_path: str


@dataclass
class AccountInfo:
    """Information about a configured account."""

    name: str
    provider: str
    credentials: str
    token: str


@dataclass
class AccountsListResult:
    """Result from listing accounts."""

    accounts: list[AccountInfo] = field(default_factory=list)


# Use SimpleConsumer[AccountsListRequest] directly or alias:
AccountsListRequestConsumer = SimpleConsumer[AccountsListRequest]


class AccountsListProcessor(SafeProcessor[AccountsListRequest, AccountsListResult]):
    def _process_safe(self, payload: AccountsListRequest) -> AccountsListResult:
        from .helpers import load_accounts

        accts = load_accounts(payload.config_path)
        return AccountsListResult(
            accounts=[
                AccountInfo(
                    name=a.get("name", _DEFAULT_ACCOUNT_NAME),
                    provider=a.get("provider", ""),
                    credentials=a.get("credentials", ""),
                    token=a.get("token", ""),
                )
                for a in accts
            ]
        )


class AccountsListProducer(AccountsResultProducer[AccountsListResult]):
    def _produce_items(self, payload: AccountsListResult) -> None:
        for a in payload.accounts:
            print(f"{a.name}\tprovider={a.provider}\tcred={a.credentials}\ttoken={a.token}")


# -----------------------------------------------------------------------------
# Export labels pipeline
# -----------------------------------------------------------------------------


@dataclass
class AccountsExportLabelsRequest:
    """Request for exporting labels from accounts."""

    config_path: str
    out_dir: str
    accounts_filter: list[str] | None = None


@dataclass
class ExportedLabelsInfo:
    """Info about exported labels for one account."""

    account_name: str
    output_path: str
    label_count: int


@dataclass
class AccountsExportLabelsResult:
    """Result from exporting labels."""

    exports: list[ExportedLabelsInfo] = field(default_factory=list)


AccountsExportLabelsRequestConsumer = SimpleConsumer[AccountsExportLabelsRequest]


class AccountsExportLabelsProcessor(SafeProcessor[AccountsExportLabelsRequest, AccountsExportLabelsResult]):
    def _process_safe(self, payload: AccountsExportLabelsRequest) -> AccountsExportLabelsResult:
        from ..yamlio import dump_config

        out_dir = Path(payload.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exports: list[ExportedLabelsInfo] = []
        for account, client in AccountAuthenticator.iter_authenticated_accounts(
            payload.config_path, payload.accounts_filter
        ):
            labels = client.list_labels()
            doc = {
                "labels": [
                    {k: v for k, v in lab.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
                    for lab in labels if lab.get("type") != "system"
                ],
                "redirects": [],
            }
            path = out_dir / f"labels_{account.get('name', 'account')}.yaml"
            dump_config(str(path), doc)
            exports.append(ExportedLabelsInfo(
                account_name=account.get("name", "account"),
                output_path=str(path),
                label_count=len(doc["labels"]),
            ))

        return AccountsExportLabelsResult(exports=exports)


class AccountsExportLabelsProducer(AccountsResultProducer[AccountsExportLabelsResult]):
    def _produce_items(self, payload: AccountsExportLabelsResult) -> None:
        for exp in payload.exports:
            print(f"Exported labels for {exp.account_name}: {exp.output_path}")


# -----------------------------------------------------------------------------
# Export filters pipeline
# -----------------------------------------------------------------------------


@dataclass
class AccountsExportFiltersRequest:
    """Request for exporting filters from accounts."""

    config_path: str
    out_dir: str
    accounts_filter: list[str] | None = None


@dataclass
class ExportedFiltersInfo:
    """Info about exported filters for one account."""

    account_name: str
    output_path: str
    filter_count: int


@dataclass
class AccountsExportFiltersResult:
    """Result from exporting filters."""

    exports: list[ExportedFiltersInfo] = field(default_factory=list)


AccountsExportFiltersRequestConsumer = SimpleConsumer[AccountsExportFiltersRequest]


class AccountsExportFiltersProcessor(SafeProcessor[AccountsExportFiltersRequest, AccountsExportFiltersResult]):
    def _process_safe(self, payload: AccountsExportFiltersRequest) -> AccountsExportFiltersResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import dump_config

        accts = load_accounts(payload.config_path)
        out_dir = Path(payload.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exports: list[ExportedFiltersInfo] = []
        for a in iter_accounts(accts, payload.accounts_filter):
            client = build_provider_for_account(a)
            client.authenticate()
            id_to_name = _build_label_id_to_name_map(client.list_labels())

            dsl = [_build_filter_dsl_entry(f, id_to_name) for f in client.list_filters()]

            path = out_dir / f"filters_{a.get('name', 'account')}.yaml"
            dump_config(str(path), {"filters": dsl})
            exports.append(ExportedFiltersInfo(
                account_name=a.get("name", "account"),
                output_path=str(path),
                filter_count=len(dsl),
            ))

        return AccountsExportFiltersResult(exports=exports)


class AccountsExportFiltersProducer(AccountsResultProducer[AccountsExportFiltersResult]):
    def _produce_items(self, payload: AccountsExportFiltersResult) -> None:
        for exp in payload.exports:
            print(f"Exported filters for {exp.account_name}: {exp.output_path}")


# -----------------------------------------------------------------------------
# Plan labels pipeline
# -----------------------------------------------------------------------------


@dataclass
class AccountsPlanLabelsRequest:
    """Request for planning labels changes."""

    config_path: str
    labels_path: str
    accounts_filter: list[str] | None = None


@dataclass
class LabelsPlanInfo:
    """Plan info for one account."""

    account_name: str
    provider: str
    to_create: int
    to_update: int


@dataclass
class AccountsPlanLabelsResult:
    """Result from planning labels."""

    plans: list[LabelsPlanInfo] = field(default_factory=list)


AccountsPlanLabelsRequestConsumer = SimpleConsumer[AccountsPlanLabelsRequest]


def _classify_label_specs(target: list, existing: dict, provider: str) -> tuple[list, list]:
    """Split label specs into (to_create, to_update) name lists."""
    to_create = []
    to_update = []
    for spec in target:
        name = spec.get("name")
        if not name:
            continue
        if name not in existing:
            to_create.append(name)
        elif _needs_label_update(spec, existing[name], provider):
            to_update.append(name)
    return to_create, to_update


def _plan_labels_for_account(a: dict, base: list) -> LabelsPlanInfo:
    """Build the labels plan for a single account."""
    from .helpers import build_provider_for_account
    from ..dsl import normalize_labels_for_outlook

    provider = (a.get("provider") or "").lower()
    client = build_provider_for_account(a)
    client.authenticate()
    existing = {lab.get("name", ""): lab for lab in client.list_labels(use_cache=True)}
    target = normalize_labels_for_outlook(base) if provider == "outlook" else base

    to_create, to_update = _classify_label_specs(target, existing, provider)

    return LabelsPlanInfo(
        account_name=a.get("name", "account"),
        provider=provider,
        to_create=len(to_create),
        to_update=len(to_update),
    )


class AccountsPlanLabelsProcessor(SafeProcessor[AccountsPlanLabelsRequest, AccountsPlanLabelsResult]):
    def _process_safe(self, payload: AccountsPlanLabelsRequest) -> AccountsPlanLabelsResult:
        from .helpers import load_accounts, iter_accounts
        from ..yamlio import load_config

        accts = load_accounts(payload.config_path)
        desired_doc = load_config(payload.labels_path)
        base = desired_doc.get("labels") or []

        plans = [
            _plan_labels_for_account(a, base)
            for a in iter_accounts(accts, payload.accounts_filter)
        ]
        return AccountsPlanLabelsResult(plans=plans)


class AccountsPlanLabelsProducer(AccountsResultProducer[AccountsPlanLabelsResult]):
    def _produce_items(self, payload: AccountsPlanLabelsResult) -> None:
        for plan in payload.plans:
            print(f"[plan-labels] {plan.account_name} provider={plan.provider} create={plan.to_create} update={plan.to_update}")


# -----------------------------------------------------------------------------
# Sync labels pipeline
# -----------------------------------------------------------------------------


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
class AccountsPlanFiltersRequest:
    """Request for planning filters changes."""

    config_path: str
    filters_path: str
    accounts_filter: list[str] | None = None


@dataclass
class FiltersPlanInfo:
    """Plan info for one account."""

    account_name: str
    provider: str
    to_create: int


@dataclass
class AccountsPlanFiltersResult:
    """Result from planning filters."""

    plans: list[FiltersPlanInfo] = field(default_factory=list)


AccountsPlanFiltersRequestConsumer = SimpleConsumer[AccountsPlanFiltersRequest]


class AccountsPlanFiltersProcessor(SafeProcessor[AccountsPlanFiltersRequest, AccountsPlanFiltersResult]):
    def _process_safe(self, payload: AccountsPlanFiltersRequest) -> AccountsPlanFiltersResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_filters_for_outlook

        accts = load_accounts(payload.config_path)
        desired_doc = load_config(payload.filters_path)
        base = desired_doc.get("filters") or []

        plans: list[FiltersPlanInfo] = []
        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()
            client = build_provider_for_account(a)
            client.authenticate()
            existing = client.list_filters(use_cache=True)

            if provider not in ("gmail", "outlook"):
                plans.append(FiltersPlanInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    to_create=-1,  # unsupported
                ))
                continue

            desired_filters = normalize_filters_for_outlook(base) if provider == "outlook" else base
            ex_keys = {canonicalize_filter(f) for f in existing}
            to_create = sum(1 for f in desired_filters if canonicalize_filter(f) not in ex_keys)

            plans.append(FiltersPlanInfo(
                account_name=a.get("name", "account"),
                provider=provider,
                to_create=to_create,
            ))

        return AccountsPlanFiltersResult(plans=plans)


class AccountsPlanFiltersProducer(AccountsResultProducer[AccountsPlanFiltersResult]):
    def _produce_items(self, payload: AccountsPlanFiltersResult) -> None:
        for plan in payload.plans:
            if plan.to_create < 0:
                print(f"[plan-filters] {plan.account_name} provider={plan.provider} not supported")
            else:
                print(f"[plan-filters] {plan.account_name} provider={plan.provider} create={plan.to_create}")


# -----------------------------------------------------------------------------
# Sync filters pipeline
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
