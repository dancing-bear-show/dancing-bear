from __future__ import annotations

from typing import Optional, Tuple  # noqa: F401 - Tuple used in return type

from ..providers.base import BaseProvider


def filters_normalize(d: dict) -> dict:
    return {k: v for k, v in (d or {}).items() if v not in (None, [], "")}


def build_criteria_from_match(match: dict) -> dict:
    m = match or {}
    criteria = {
        "from": m.get("from"),
        "to": m.get("to"),
        "subject": m.get("subject"),
        "query": m.get("query"),
        "negatedQuery": m.get("negatedQuery"),
        "hasAttachment": m.get("hasAttachment"),
        "size": m.get("size"),
        "sizeComparison": m.get("sizeComparison"),
    }
    return filters_normalize(criteria)


def build_gmail_query(
    match: dict,
    days: Optional[int] = None,
    only_inbox: bool = False,
    older_than_days: Optional[int] = None,
) -> str:
    parts = []
    m = match or {}
    if m.get("from"):
        parts.append(f"from:({m['from']})")
    if m.get("to"):
        parts.append(f"to:({m['to']})")
    if m.get("subject"):
        subj = m['subject']
        if ' ' in subj:
            parts.append(f"subject:\"{subj}\"")
        else:
            parts.append(f"subject:{subj}")
    if m.get("query"):
        parts.append(str(m['query']))
    if m.get("negatedQuery"):
        parts.append(f"-({m['negatedQuery']})")
    if m.get("hasAttachment"):
        parts.append("has:attachment")
    if days:
        parts.append(f"newer_than:{int(days)}d")
    if older_than_days:
        parts.append(f"older_than:{int(older_than_days)}d")
    if only_inbox:
        parts.append("in:inbox")
    return " ".join(parts).strip()


def _resolve_label_ids(client: BaseProvider, names: list, name_to_id: dict) -> list[str]:
    """Resolve label names to IDs, creating labels if needed."""
    ids = []
    for n in names:
        if not n:
            continue
        if isinstance(n, str) and n.isupper():
            ids.append(n)
        else:
            ids.append(name_to_id.get(n) or client.ensure_label(n))
    return ids


def action_to_label_changes(client: BaseProvider, action: dict) -> Tuple[list[str], list[str]]:
    action = action or {}
    name_to_id = client.get_label_id_map()
    add_ids = _resolve_label_ids(client, action.get("add") or [], name_to_id)
    rem_ids = _resolve_label_ids(client, action.get("remove") or [], name_to_id)
    return add_ids, rem_ids


# Category normalization (Gmail tabs)
_CATEGORY_MAP = {
    "promotions": "CATEGORY_PROMOTIONS",
    "forums": "CATEGORY_FORUMS",
    "updates": "CATEGORY_UPDATES",
    "social": "CATEGORY_SOCIAL",
    "personal": "CATEGORY_PERSONAL",
}


def _map_category(name: str) -> Optional[str]:
    """Map a friendly category name to a Gmail system label, or None."""
    return _CATEGORY_MAP.get(name.strip().lower())


def _append_mapped_categories(cats: list, seq) -> None:
    """Append mapped category labels from a sequence into cats."""
    if not isinstance(seq, list):
        return
    for it in seq:
        if isinstance(it, str):
            mapped = _map_category(it)
            if mapped:
                cats.append(mapped)


def categories_to_system_labels(action_spec: dict) -> list[str]:
    """Expand friendly category keys to Gmail system label names.

    Supports:
    - action.categorizeAs: str
    - action.categorize: str | list[str]
    - action.categories: list[str]
    """
    if not isinstance(action_spec, dict):
        return []
    cats: list[str] = []
    val = action_spec.get("categorizeAs") or action_spec.get("categorize")
    if isinstance(val, str):
        mapped = _map_category(val)
        if mapped:
            cats.append(mapped)
    _append_mapped_categories(cats, action_spec.get("categories"))
    _append_mapped_categories(cats, action_spec.get("categorize"))
    return cats


# Backwards-compatible alias
expand_categories = categories_to_system_labels
