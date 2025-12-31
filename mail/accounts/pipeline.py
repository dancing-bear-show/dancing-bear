"""Pipeline primitives for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, TypeVar

from core.pipeline import Producer, ResultEnvelope, SafeProcessor, RequestConsumer

# -----------------------------------------------------------------------------
# Shared abstractions
# -----------------------------------------------------------------------------

T = TypeVar("T")
R = TypeVar("R")


# Use RequestConsumer from core.pipeline instead of defining SimpleConsumer
# (kept as alias for backward compatibility in this file)
SimpleConsumer = RequestConsumer


class AccountsResultProducer(Producer[ResultEnvelope[R]], Generic[R]):
    """Base producer with common error handling for accounts operations."""

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run

    def produce(self, result: ResultEnvelope[R]) -> None:
        if not result.ok():
            print(f"Error: {(result.diagnostics or {}).get('message', 'Failed')}")
            return
        self._produce_items(result.unwrap())

    def _produce_items(self, payload: R) -> None:
        """Override to format and print result items."""
        raise NotImplementedError


class AccountAuthenticator:
    """Factory for creating authenticated account providers."""

    @staticmethod
    def iter_authenticated_accounts(config_path: str, accounts_filter: Optional[List[str]] = None):
        """Load accounts, filter, build providers, and authenticate.

        Yields:
            Tuple of (account_dict, authenticated_client)
        """
        from .helpers import load_accounts, iter_accounts, build_provider_for_account

        accts = load_accounts(config_path)
        for account in iter_accounts(accts, accounts_filter):
            client = build_provider_for_account(account)
            client.authenticate()
            yield account, client


def canonicalize_filter(f: Dict[str, Any]) -> str:
    """Canonical string representation of a filter for comparison."""
    crit = f.get("criteria") or f.get("match") or {}
    act = f.get("action") or {}
    add_ids = act.get("addLabelIds") or act.get("add") or []
    return str({
        "from": crit.get("from"),
        "to": crit.get("to"),
        "subject": crit.get("subject"),
        "query": crit.get("query"),
        "add": tuple(sorted(add_ids)),
        "forward": act.get("forward"),
    })


def _build_label_id_to_name_map(labels: list) -> Dict[str, str]:
    """Build mapping from label IDs to names."""
    return {lab.get("id", ""): lab.get("name", "") for lab in labels}


def _convert_label_ids_to_names(ids: Optional[list], id_to_name: Dict[str, str]) -> list:
    """Convert list of label IDs to names using provided mapping."""
    return [id_to_name.get(x) for x in ids or [] if id_to_name.get(x)]


def _extract_filter_criteria(criteria_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant filter criteria fields."""
    allowed_fields = ("from", "to", "subject", "query", "negatedQuery", "hasAttachment", "size", "sizeComparison")
    return {k: v for k, v in criteria_dict.items() if k in allowed_fields and v not in (None, "")}


def _build_filter_dsl_entry(filter_obj: Dict[str, Any], id_to_name: Dict[str, str]) -> Dict[str, Any]:
    """Build a DSL filter entry from a raw filter object."""
    crit = filter_obj.get("criteria", {}) or {}
    act = filter_obj.get("action", {}) or {}

    entry: Dict[str, Any] = {
        "match": _extract_filter_criteria(crit),
        "action": {},
    }

    if act.get("forward"):
        entry["action"]["forward"] = act["forward"]
    if act.get("addLabelIds"):
        entry["action"]["add"] = _convert_label_ids_to_names(act.get("addLabelIds"), id_to_name)
    if act.get("removeLabelIds"):
        entry["action"]["remove"] = _convert_label_ids_to_names(act.get("removeLabelIds"), id_to_name)

    return entry


def _needs_label_update(spec: Dict[str, Any], current: Dict[str, Any], provider: str) -> bool:
    """Check if label needs updating based on spec vs current state."""
    if provider == "gmail":
        for k in ("color", "labelListVisibility", "messageListVisibility"):
            if spec.get(k) and spec.get(k) != current.get(k):
                return True
    elif provider == "outlook":
        if spec.get("color") and spec.get("color") != current.get("color"):
            return True
    return False


def _build_label_update_dict(name: str, spec: Dict[str, Any], current: Dict[str, Any], provider: str) -> Optional[Dict[str, Any]]:
    """Build update dict for a label if changes are needed."""
    upd = {"name": name}
    changed = False

    if provider == "gmail":
        for k in ("color", "labelListVisibility", "messageListVisibility"):
            if spec.get(k) and spec.get(k) != current.get(k):
                upd[k] = spec[k]
                changed = True
    elif provider == "outlook":
        if spec.get("color") and spec.get("color") != current.get("color"):
            upd["color"] = spec["color"]
            changed = True

    return upd if changed else None


def _build_outlook_filter_action(action_spec: Dict[str, Any], name_to_id: Dict[str, str]) -> Dict[str, Any]:
    """Build Outlook filter action from spec."""
    from ..outlook.helpers import norm_label_name_outlook

    action: Dict[str, Any] = {}
    if action_spec.get("add"):
        action["addLabelIds"] = [
            name_to_id.get(x) or name_to_id.get(norm_label_name_outlook(x))
            for x in action_spec["add"]
        ]
        action["addLabelIds"] = [x for x in action["addLabelIds"] if x]
    if action_spec.get("forward"):
        action["forward"] = action_spec["forward"]
    return action


def _sync_outlook_filters(client, desired_filters: list, existing_filters: list, name_to_id: Dict[str, str], dry_run: bool) -> tuple[int, int]:
    """Sync Outlook filters and return (created, errors) counts."""
    existing_keys = {canonicalize_filter(f): f for f in existing_filters}
    created = 0
    errors = 0

    for spec in desired_filters:
        match = spec.get("match") or {}
        action_spec = spec.get("action") or {}
        criteria = {k: v for k, v in match.items() if k in ("from", "to", "subject")}
        action = _build_outlook_filter_action(action_spec, name_to_id)

        key = str({
            "from": criteria.get("from"),
            "to": criteria.get("to"),
            "subject": criteria.get("subject"),
            "add": tuple(sorted(action.get("addLabelIds", []) or [])),
            "forward": action.get("forward"),
        })

        if key in existing_keys:
            continue

        if not dry_run:
            try:
                client.create_filter(criteria, action)
                created += 1
            except Exception:  # nosec B110 - continue on filter creation errors
                errors += 1
        else:
            created += 1

    return created, errors


def _sync_labels_for_account(client, desired: list, existing: Dict[str, Any], provider: str, dry_run: bool) -> tuple[int, int]:
    """Sync labels for an account and return (created, updated) counts."""
    created = 0
    updated = 0

    for spec in desired:
        name = spec.get("name")
        if not name:
            continue

        # Create new labels
        if name not in existing:
            if not dry_run:
                client.create_label(**spec)
            created += 1
            continue

        # Update existing labels if needed
        cur = existing[name]
        upd = _build_label_update_dict(name, spec, cur, provider)
        if upd and not dry_run:
            client.update_label(cur.get("id", ""), upd)
        if upd:
            updated += 1

    return created, updated


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

    accounts: List[AccountInfo] = field(default_factory=list)


# Use SimpleConsumer[AccountsListRequest] directly or alias:
AccountsListRequestConsumer = SimpleConsumer[AccountsListRequest]


class AccountsListProcessor(SafeProcessor[AccountsListRequest, AccountsListResult]):
    def _process_safe(self, payload: AccountsListRequest) -> AccountsListResult:
        from .helpers import load_accounts

        accts = load_accounts(payload.config_path)
        return AccountsListResult(
            accounts=[
                AccountInfo(
                    name=a.get("name", "<noname>"),
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
    accounts_filter: Optional[List[str]] = None


@dataclass
class ExportedLabelsInfo:
    """Info about exported labels for one account."""

    account_name: str
    output_path: str
    label_count: int


@dataclass
class AccountsExportLabelsResult:
    """Result from exporting labels."""

    exports: List[ExportedLabelsInfo] = field(default_factory=list)


AccountsExportLabelsRequestConsumer = SimpleConsumer[AccountsExportLabelsRequest]


class AccountsExportLabelsProcessor(SafeProcessor[AccountsExportLabelsRequest, AccountsExportLabelsResult]):
    def _process_safe(self, payload: AccountsExportLabelsRequest) -> AccountsExportLabelsResult:
        from ..yamlio import dump_config

        out_dir = Path(payload.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exports: List[ExportedLabelsInfo] = []
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
    accounts_filter: Optional[List[str]] = None


@dataclass
class ExportedFiltersInfo:
    """Info about exported filters for one account."""

    account_name: str
    output_path: str
    filter_count: int


@dataclass
class AccountsExportFiltersResult:
    """Result from exporting filters."""

    exports: List[ExportedFiltersInfo] = field(default_factory=list)


AccountsExportFiltersRequestConsumer = SimpleConsumer[AccountsExportFiltersRequest]


class AccountsExportFiltersProcessor(SafeProcessor[AccountsExportFiltersRequest, AccountsExportFiltersResult]):
    def _process_safe(self, payload: AccountsExportFiltersRequest) -> AccountsExportFiltersResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import dump_config

        accts = load_accounts(payload.config_path)
        out_dir = Path(payload.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exports: List[ExportedFiltersInfo] = []
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
    accounts_filter: Optional[List[str]] = None


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

    plans: List[LabelsPlanInfo] = field(default_factory=list)


AccountsPlanLabelsRequestConsumer = SimpleConsumer[AccountsPlanLabelsRequest]


class AccountsPlanLabelsProcessor(SafeProcessor[AccountsPlanLabelsRequest, AccountsPlanLabelsResult]):
    def _process_safe(self, payload: AccountsPlanLabelsRequest) -> AccountsPlanLabelsResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_labels_for_outlook

        accts = load_accounts(payload.config_path)
        desired_doc = load_config(payload.labels_path)
        base = desired_doc.get("labels") or []

        plans: List[LabelsPlanInfo] = []
        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()
            client = build_provider_for_account(a)
            client.authenticate()
            existing = {lab.get("name", ""): lab for lab in client.list_labels(use_cache=True)}
            target = normalize_labels_for_outlook(base) if provider == "outlook" else base

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

            plans.append(LabelsPlanInfo(
                account_name=a.get("name", "account"),
                provider=provider,
                to_create=len(to_create),
                to_update=len(to_update),
            ))

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
    accounts_filter: Optional[List[str]] = None
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

    synced: List[SyncedLabelInfo] = field(default_factory=list)


AccountsSyncLabelsRequestConsumer = SimpleConsumer[AccountsSyncLabelsRequest]


class AccountsSyncLabelsProcessor(SafeProcessor[AccountsSyncLabelsRequest, AccountsSyncLabelsResult]):
    def _process_safe(self, payload: AccountsSyncLabelsRequest) -> AccountsSyncLabelsResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_labels_for_outlook

        accts = load_accounts(payload.config_path)
        desired_doc = load_config(payload.labels_path)
        desired_base = desired_doc.get("labels") or []

        synced: List[SyncedLabelInfo] = []
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
    accounts_filter: Optional[List[str]] = None


@dataclass
class FiltersPlanInfo:
    """Plan info for one account."""

    account_name: str
    provider: str
    to_create: int


@dataclass
class AccountsPlanFiltersResult:
    """Result from planning filters."""

    plans: List[FiltersPlanInfo] = field(default_factory=list)


AccountsPlanFiltersRequestConsumer = SimpleConsumer[AccountsPlanFiltersRequest]


class AccountsPlanFiltersProcessor(SafeProcessor[AccountsPlanFiltersRequest, AccountsPlanFiltersResult]):
    def _process_safe(self, payload: AccountsPlanFiltersRequest) -> AccountsPlanFiltersResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_filters_for_outlook

        accts = load_accounts(payload.config_path)
        desired_doc = load_config(payload.filters_path)
        base = desired_doc.get("filters") or []

        plans: List[FiltersPlanInfo] = []
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
    accounts_filter: Optional[List[str]] = None
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

    synced: List[SyncedFiltersInfo] = field(default_factory=list)


AccountsSyncFiltersRequestConsumer = SimpleConsumer[AccountsSyncFiltersRequest]


class AccountsSyncFiltersProcessor(SafeProcessor[AccountsSyncFiltersRequest, AccountsSyncFiltersResult]):
    def _process_safe(self, payload: AccountsSyncFiltersRequest) -> AccountsSyncFiltersResult:
        import argparse
        from .helpers import load_accounts, iter_accounts, build_client_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_filters_for_outlook
        from ..filters.commands import run_filters_sync

        accts = load_accounts(payload.config_path)
        synced: List[SyncedFiltersInfo] = []

        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()

            if provider == "gmail":
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
                synced.append(SyncedFiltersInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    created=-1,  # delegated to run_filters_sync
                    errors=0,
                ))
            elif provider == "outlook":
                client = build_client_for_account(a)
                client.authenticate()
                doc = load_config(payload.filters_path)
                desired = normalize_filters_for_outlook(doc.get("filters") or [])
                existing = client.list_filters()
                name_to_id = client.get_label_id_map()

                created, errors = _sync_outlook_filters(client, desired, existing, name_to_id, payload.dry_run)

                synced.append(SyncedFiltersInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    created=created,
                    errors=errors,
                ))
            else:
                synced.append(SyncedFiltersInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    created=-1,
                    errors=0,
                ))

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
    accounts_filter: Optional[List[str]] = None


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

    exports: List[ExportedSignaturesInfo] = field(default_factory=list)


AccountsExportSignaturesRequestConsumer = SimpleConsumer[AccountsExportSignaturesRequest]


class AccountsExportSignaturesProcessor(SafeProcessor[AccountsExportSignaturesRequest, AccountsExportSignaturesResult]):
    def _process_safe(self, payload: AccountsExportSignaturesRequest) -> AccountsExportSignaturesResult:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import dump_config

        accts = load_accounts(payload.config_path)
        out_dir = Path(payload.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exports: List[ExportedSignaturesInfo] = []
        for a in iter_accounts(accts, payload.accounts_filter):
            name = a.get("name", "account")
            provider = (a.get("provider") or "").lower()
            path = out_dir / f"signatures_{name}.yaml"
            assets = out_dir / f"{name}_assets"
            assets.mkdir(parents=True, exist_ok=True)
            doc: Dict[str, Any] = {"signatures": {"gmail": [], "ios": {}, "outlook": []}}
            sig_count = 0

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
                sig_count = len(doc["signatures"]["gmail"])
                prim = next((s for s in doc["signatures"]["gmail"] if s.get("isPrimary")), None)
                if prim and prim.get("signature_html"):
                    doc["signatures"]["default_html"] = prim["signature_html"]
                    (assets / "ios_signature.html").write_text(prim["signature_html"], encoding="utf-8")
            elif provider == "outlook":
                (assets / "OUTLOOK_README.txt").write_text(
                    "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                    "Use ios_signature.html exported from a Gmail account, or paste HTML manually.",
                    encoding="utf-8",
                )

            dump_config(str(path), doc)
            exports.append(ExportedSignaturesInfo(
                account_name=name,
                provider=provider,
                output_path=str(path),
                signature_count=sig_count,
            ))

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
    accounts_filter: Optional[List[str]] = None
    send_as: Optional[str] = None
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

    synced: List[SyncedSignaturesInfo] = field(default_factory=list)


AccountsSyncSignaturesRequestConsumer = SimpleConsumer[AccountsSyncSignaturesRequest]


class AccountsSyncSignaturesProcessor(SafeProcessor[AccountsSyncSignaturesRequest, AccountsSyncSignaturesResult]):
    def _process_safe(self, payload: AccountsSyncSignaturesRequest) -> AccountsSyncSignaturesResult:
        import argparse
        from .helpers import load_accounts, iter_accounts
        from ..signatures.commands import run_signatures_sync

        accts = load_accounts(payload.config_path)
        synced: List[SyncedSignaturesInfo] = []

        for a in iter_accounts(accts, payload.accounts_filter):
            provider = (a.get("provider") or "").lower()

            if provider == "gmail":
                ns = argparse.Namespace(
                    credentials=a.get("credentials"),
                    token=a.get("token"),
                    config=payload.config_path,
                    send_as=payload.send_as,
                    dry_run=payload.dry_run,
                    account_display_name=a.get("display_name"),
                )
                run_signatures_sync(ns)
                synced.append(SyncedSignaturesInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    status="delegated",
                ))
            elif provider == "outlook":
                assets = Path("signatures_assets")
                assets.mkdir(parents=True, exist_ok=True)
                (assets / "OUTLOOK_README.txt").write_text(
                    "Outlook signatures are not exposed via Microsoft Graph v1.0.\n"
                    "Use ios_signature.html or paste HTML manually.",
                    encoding="utf-8",
                )
                synced.append(SyncedSignaturesInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    status="wrote_guidance",
                ))
            else:
                synced.append(SyncedSignaturesInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    status="unsupported",
                ))

        return AccountsSyncSignaturesResult(synced=synced)


class AccountsSyncSignaturesProducer(AccountsResultProducer[AccountsSyncSignaturesResult]):
    def _produce_items(self, payload: AccountsSyncSignaturesResult) -> None:
        for info in payload.synced:
            if info.status == "delegated":
                print(f"[signatures sync] {info.account_name} provider={info.provider} (delegated)")
            elif info.status == "wrote_guidance":
                print(f"[signatures sync] {info.account_name} provider={info.provider} wrote guidance to signatures_assets/")
            else:
                print(f"[signatures sync] {info.account_name} provider={info.provider} status={info.status}")
