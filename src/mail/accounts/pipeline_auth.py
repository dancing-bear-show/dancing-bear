"""Auth helpers and shared pipeline primitives for accounts commands."""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from core.pipeline import Producer, ResultEnvelope, RequestConsumer

_LOG_PREFIX = "[signatures sync] "

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
    def iter_authenticated_accounts(config_path: str, accounts_filter: list[str] | None = None):
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


def canonicalize_filter(f: dict[str, Any]) -> str:
    """Canonical string representation of a filter for comparison."""
    crit = f.get("criteria") or f.get("match") or {}
    act = f.get("action") or {}
    _raw_ids = act.get("addLabelIds") or act.get("add") or []
    add_ids: list = _raw_ids if isinstance(_raw_ids, list) else []
    return str({
        "from": crit.get("from"),
        "to": crit.get("to"),
        "subject": crit.get("subject"),
        "query": crit.get("query"),
        "add": tuple(sorted(add_ids)),
        "forward": act.get("forward"),
    })


def _build_label_id_to_name_map(labels: list) -> dict[str, str]:
    """Build mapping from label IDs to names."""
    return {lab.get("id", ""): lab.get("name", "") for lab in labels}


def _convert_label_ids_to_names(ids: list | None, id_to_name: dict[str, str]) -> list:
    """Convert list of label IDs to names using provided mapping."""
    return [id_to_name.get(x) for x in ids or [] if id_to_name.get(x)]


def _extract_filter_criteria(criteria_dict: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant filter criteria fields."""
    allowed_fields = ("from", "to", "subject", "query", "negatedQuery", "hasAttachment", "size", "sizeComparison")
    return {k: v for k, v in criteria_dict.items() if k in allowed_fields and v not in (None, "")}


def _build_filter_dsl_entry(filter_obj: dict[str, Any], id_to_name: dict[str, str]) -> dict[str, Any]:
    """Build a DSL filter entry from a raw filter object."""
    crit = filter_obj.get("criteria", {}) or {}
    act = filter_obj.get("action", {}) or {}

    entry: dict[str, Any] = {
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


# Fields checked for drift, keyed by provider. Gmail supports visibility fields;
# Outlook (via Graph categories) only supports color.
_LABEL_UPDATE_FIELDS_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "gmail": ("color", "labelListVisibility", "messageListVisibility"),
    "outlook": ("color",),
}


def _changed_label_fields(spec: dict[str, Any], current: dict[str, Any], provider: str) -> dict[str, Any]:
    """Return the subset of provider-relevant fields that differ between spec and current."""
    fields = _LABEL_UPDATE_FIELDS_BY_PROVIDER.get(provider, ())
    return {k: spec[k] for k in fields if spec.get(k) and spec.get(k) != current.get(k)}


def _needs_label_update(spec: dict[str, Any], current: dict[str, Any], provider: str) -> bool:
    """Check if label needs updating based on spec vs current state."""
    return bool(_changed_label_fields(spec, current, provider))


def _build_label_update_dict(name: str, spec: dict[str, Any], current: dict[str, Any], provider: str) -> dict[str, Any] | None:
    """Build update dict for a label if changes are needed."""
    changed = _changed_label_fields(spec, current, provider)
    return {"name": name, **changed} if changed else None


def _build_outlook_filter_action(action_spec: dict[str, Any], name_to_id: dict[str, str]) -> dict[str, Any]:
    """Build Outlook filter action from spec."""
    from ..outlook.helpers import norm_label_name_outlook

    action: dict[str, Any] = {}
    if action_spec.get("add"):
        action["addLabelIds"] = [
            name_to_id.get(x) or name_to_id.get(norm_label_name_outlook(x))
            for x in action_spec["add"]
        ]
        action["addLabelIds"] = [x for x in action["addLabelIds"] if x]
    if action_spec.get("forward"):
        action["forward"] = action_spec["forward"]
    return action


def _outlook_filter_key(criteria: dict[str, Any], action: dict[str, Any]) -> str:
    """Canonical comparison key for a built Outlook filter criteria/action pair."""
    return str({
        "from": criteria.get("from"),
        "to": criteria.get("to"),
        "subject": criteria.get("subject"),
        "add": tuple(sorted(action.get("addLabelIds", []) or [])),
        "forward": action.get("forward"),
    })


def _sync_one_outlook_filter(
    client, spec: dict[str, Any], existing_keys: set, name_to_id: dict[str, str], dry_run: bool
) -> tuple[int, int]:
    """Sync a single Outlook filter spec. Returns (created_delta, errors_delta)."""
    match = spec.get("match") or {}
    action_spec = spec.get("action") or {}
    criteria = {k: v for k, v in match.items() if k in ("from", "to", "subject")}
    action = _build_outlook_filter_action(action_spec, name_to_id)

    if _outlook_filter_key(criteria, action) in existing_keys:
        return 0, 0

    if dry_run:
        return 1, 0

    try:
        client.create_filter(criteria, action)
        return 1, 0
    except Exception:  # nosec B110 - continue on filter creation errors
        return 0, 1


def _sync_outlook_filters(client, desired_filters: list, existing_filters: list, name_to_id: dict[str, str], dry_run: bool) -> tuple[int, int]:
    """Sync Outlook filters and return (created, errors) counts."""
    existing_keys = {canonicalize_filter(f) for f in existing_filters}
    created = errors = 0
    for spec in desired_filters:
        c, e = _sync_one_outlook_filter(client, spec, existing_keys, name_to_id, dry_run)
        created += c
        errors += e
    return created, errors


def _sync_one_label(client, spec: dict[str, Any], existing: dict[str, Any], provider: str, dry_run: bool) -> tuple[int, int]:
    """Sync a single label spec. Returns (created_delta, updated_delta)."""
    name = spec.get("name")
    if not name:
        return 0, 0

    if name not in existing:
        if not dry_run:
            client.create_label(**spec)
        return 1, 0

    upd = _build_label_update_dict(name, spec, existing[name], provider)
    if not upd:
        return 0, 0
    if not dry_run:
        client.update_label(existing[name].get("id", ""), upd)
    return 0, 1


def _sync_labels_for_account(client, desired: list, existing: dict[str, Any], provider: str, dry_run: bool) -> tuple[int, int]:
    """Sync labels for an account and return (created, updated) counts."""
    created = updated = 0
    for spec in desired:
        c, u = _sync_one_label(client, spec, existing, provider, dry_run)
        created += c
        updated += u
    return created, updated
