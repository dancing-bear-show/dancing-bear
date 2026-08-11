"""Plan labels and filters pipeline implementations for accounts commands."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.pipeline import SafeProcessor

from .pipeline_auth import (
    AccountsResultProducer,
    SimpleConsumer,
    _needs_label_update,
    canonicalize_filter,
)


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
