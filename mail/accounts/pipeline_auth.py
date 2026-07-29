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
    add_ids = act.get("addLabelIds") or act.get("add") or []
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


def _needs_label_update(spec: dict[str, Any], current: dict[str, Any], provider: str) -> bool:
    """Check if label needs updating based on spec vs current state."""
    if provider == "gmail":
        for k in ("color", "labelListVisibility", "messageListVisibility"):
            if spec.get(k) and spec.get(k) != current.get(k):
                return True
    elif provider == "outlook":
        if spec.get("color") and spec.get("color") != current.get("color"):
            return True
    return False


def _build_label_update_dict(name: str, spec: dict[str, Any], current: dict[str, Any], provider: str) -> dict[str, Any] | None:
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


def _sync_outlook_filters(client, desired_filters: list, existing_filters: list, name_to_id: dict[str, str], dry_run: bool) -> tuple[int, int]:
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


def _sync_labels_for_account(client, desired: list, existing: dict[str, Any], provider: str, dry_run: bool) -> tuple[int, int]:
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
