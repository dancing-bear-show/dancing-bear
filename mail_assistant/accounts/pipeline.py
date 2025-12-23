from __future__ import annotations

"""Pipeline primitives for accounts commands."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope


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


class AccountsListRequestConsumer(Consumer[AccountsListRequest]):
    def __init__(self, request: AccountsListRequest) -> None:
        self._request = request

    def consume(self) -> AccountsListRequest:
        return self._request


class AccountsListProcessor(Processor[AccountsListRequest, ResultEnvelope[AccountsListResult]]):
    def process(self, payload: AccountsListRequest) -> ResultEnvelope[AccountsListResult]:
        from .helpers import load_accounts

        try:
            accts = load_accounts(payload.config_path)
            result = AccountsListResult(
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
            return ResultEnvelope(status="success", payload=result)
        except Exception as e:
            return ResultEnvelope(status="error", diagnostics={"message": str(e)})


class AccountsListProducer(Producer[ResultEnvelope[AccountsListResult]]):
    def produce(self, result: ResultEnvelope[AccountsListResult]) -> None:
        if not result.ok():
            print(f"Error: {(result.diagnostics or {}).get('message', 'Failed')}")
            return
        assert result.payload is not None
        for a in result.payload.accounts:
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


class AccountsExportLabelsRequestConsumer(Consumer[AccountsExportLabelsRequest]):
    def __init__(self, request: AccountsExportLabelsRequest) -> None:
        self._request = request

    def consume(self) -> AccountsExportLabelsRequest:
        return self._request


class AccountsExportLabelsProcessor(Processor[AccountsExportLabelsRequest, ResultEnvelope[AccountsExportLabelsResult]]):
    def process(self, payload: AccountsExportLabelsRequest) -> ResultEnvelope[AccountsExportLabelsResult]:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import dump_config

        try:
            accts = load_accounts(payload.config_path)
            out_dir = Path(payload.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            exports: List[ExportedLabelsInfo] = []
            for a in iter_accounts(accts, payload.accounts_filter):
                client = build_provider_for_account(a)
                client.authenticate()
                labels = client.list_labels()
                doc = {
                    "labels": [
                        {k: v for k, v in lab.items() if k in ("name", "color", "labelListVisibility", "messageListVisibility")}
                        for lab in labels if lab.get("type") != "system"
                    ],
                    "redirects": [],
                }
                path = out_dir / f"labels_{a.get('name', 'account')}.yaml"
                dump_config(str(path), doc)
                exports.append(ExportedLabelsInfo(
                    account_name=a.get("name", "account"),
                    output_path=str(path),
                    label_count=len(doc["labels"]),
                ))

            return ResultEnvelope(status="success", payload=AccountsExportLabelsResult(exports=exports))
        except Exception as e:
            return ResultEnvelope(status="error", diagnostics={"message": str(e)})


class AccountsExportLabelsProducer(Producer[ResultEnvelope[AccountsExportLabelsResult]]):
    def produce(self, result: ResultEnvelope[AccountsExportLabelsResult]) -> None:
        if not result.ok():
            print(f"Error: {(result.diagnostics or {}).get('message', 'Failed')}")
            return
        assert result.payload is not None
        for exp in result.payload.exports:
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


class AccountsExportFiltersRequestConsumer(Consumer[AccountsExportFiltersRequest]):
    def __init__(self, request: AccountsExportFiltersRequest) -> None:
        self._request = request

    def consume(self) -> AccountsExportFiltersRequest:
        return self._request


class AccountsExportFiltersProcessor(Processor[AccountsExportFiltersRequest, ResultEnvelope[AccountsExportFiltersResult]]):
    def process(self, payload: AccountsExportFiltersRequest) -> ResultEnvelope[AccountsExportFiltersResult]:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import dump_config

        try:
            accts = load_accounts(payload.config_path)
            out_dir = Path(payload.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            exports: List[ExportedFiltersInfo] = []
            for a in iter_accounts(accts, payload.accounts_filter):
                client = build_provider_for_account(a)
                client.authenticate()
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

                path = out_dir / f"filters_{a.get('name', 'account')}.yaml"
                dump_config(str(path), {"filters": dsl})
                exports.append(ExportedFiltersInfo(
                    account_name=a.get("name", "account"),
                    output_path=str(path),
                    filter_count=len(dsl),
                ))

            return ResultEnvelope(status="success", payload=AccountsExportFiltersResult(exports=exports))
        except Exception as e:
            return ResultEnvelope(status="error", diagnostics={"message": str(e)})


class AccountsExportFiltersProducer(Producer[ResultEnvelope[AccountsExportFiltersResult]]):
    def produce(self, result: ResultEnvelope[AccountsExportFiltersResult]) -> None:
        if not result.ok():
            print(f"Error: {(result.diagnostics or {}).get('message', 'Failed')}")
            return
        assert result.payload is not None
        for exp in result.payload.exports:
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


class AccountsPlanLabelsRequestConsumer(Consumer[AccountsPlanLabelsRequest]):
    def __init__(self, request: AccountsPlanLabelsRequest) -> None:
        self._request = request

    def consume(self) -> AccountsPlanLabelsRequest:
        return self._request


class AccountsPlanLabelsProcessor(Processor[AccountsPlanLabelsRequest, ResultEnvelope[AccountsPlanLabelsResult]]):
    def process(self, payload: AccountsPlanLabelsRequest) -> ResultEnvelope[AccountsPlanLabelsResult]:
        from .helpers import load_accounts, iter_accounts, build_provider_for_account
        from ..yamlio import load_config
        from ..dsl import normalize_labels_for_outlook

        try:
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

                plans.append(LabelsPlanInfo(
                    account_name=a.get("name", "account"),
                    provider=provider,
                    to_create=len(to_create),
                    to_update=len(to_update),
                ))

            return ResultEnvelope(status="success", payload=AccountsPlanLabelsResult(plans=plans))
        except Exception as e:
            return ResultEnvelope(status="error", diagnostics={"message": str(e)})


class AccountsPlanLabelsProducer(Producer[ResultEnvelope[AccountsPlanLabelsResult]]):
    def produce(self, result: ResultEnvelope[AccountsPlanLabelsResult]) -> None:
        if not result.ok():
            print(f"Error: {(result.diagnostics or {}).get('message', 'Failed')}")
            return
        assert result.payload is not None
        for plan in result.payload.plans:
            print(f"[plan-labels] {plan.account_name} provider={plan.provider} create={plan.to_create} update={plan.to_update}")
