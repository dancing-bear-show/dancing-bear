from __future__ import annotations

from typing import Optional, Tuple, List

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


def action_to_label_changes(client: BaseProvider, action: dict) -> Tuple[list[str], list[str]]:
    action = action or {}
    add_names = action.get("add") or []
    rem_names = action.get("remove") or []
    # Provider should support these helpers (Gmail/Outlook adapters do)
    name_to_id = client.get_label_id_map()
    add_ids = []
    rem_ids = []
    for n in add_names:
        if not n:
            continue
        if isinstance(n, str) and n.isupper():
            add_ids.append(n)
        else:
            add_ids.append(name_to_id.get(n) or client.ensure_label(n))
    for n in rem_names:
        if not n:
            continue
        if isinstance(n, str) and n.isupper():
            rem_ids.append(n)
        else:
            rem_ids.append(name_to_id.get(n) or client.ensure_label(n))
    return add_ids, rem_ids


# Category normalization (Gmail tabs)
_CATEGORY_MAP = {
    "promotions": "CATEGORY_PROMOTIONS",
    "forums": "CATEGORY_FORUMS",
    "updates": "CATEGORY_UPDATES",
    "social": "CATEGORY_SOCIAL",
    "personal": "CATEGORY_PERSONAL",
}


def categories_to_system_labels(action_spec: dict) -> list[str]:
    """Expand friendly category keys to Gmail system label names.

    Supports:
    - action.categorizeAs: str
    - action.categorize: str | list[str]
    - action.categories: list[str]
    """
    cats: list[str] = []
    if not isinstance(action_spec, dict):
        return cats
    # Single value forms
    val = action_spec.get("categorizeAs") or action_spec.get("categorize")
    if isinstance(val, str):
        key = val.strip().lower()
        if key in _CATEGORY_MAP:
            cats.append(_CATEGORY_MAP[key])
    # Sequence forms
    for seq_key in ("categories", "categorize"):
        v = action_spec.get(seq_key)
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str):
                    key = it.strip().lower()
                    if key in _CATEGORY_MAP:
                        cats.append(_CATEGORY_MAP[key])
    return cats


def expand_categories(action_spec: dict) -> List[str]:
    """Return Gmail system labels for friendly category spec fields."""

    mapping = {
        "promotions": "CATEGORY_PROMOTIONS",
        "forums": "CATEGORY_FORUMS",
        "updates": "CATEGORY_UPDATES",
        "social": "CATEGORY_SOCIAL",
        "personal": "CATEGORY_PERSONAL",
    }
    cats: List[str] = []
    if not isinstance(action_spec, dict):
        return cats
    val = action_spec.get("categorizeAs") or action_spec.get("categorize")
    if isinstance(val, str):
        key = val.strip().lower()
        if key in mapping:
            cats.append(mapping[key])
    for seq_key in ("categories", "categorize"):
        v = action_spec.get(seq_key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    key = item.strip().lower()
                    if key in mapping:
                        cats.append(mapping[key])
    return cats
