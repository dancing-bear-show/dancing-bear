"""List, export, plan, and sync pipeline implementations for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.pipeline import SafeProcessor

from .pipeline_auth import (
    AccountsResultProducer,
    SimpleConsumer,
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
