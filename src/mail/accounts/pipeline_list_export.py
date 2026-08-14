"""Export labels and filters pipeline implementations for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.pipeline import SafeProcessor

from .pipeline_auth import (
    AccountAuthenticator,
    AccountsResultProducer,
    SimpleConsumer,
    _build_label_id_to_name_map,
    _build_filter_dsl_entry,
)


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
        from core.yamlio import dump_config

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
        from core.yamlio import dump_config

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
