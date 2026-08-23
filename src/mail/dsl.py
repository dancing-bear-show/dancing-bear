from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .outlook.helpers import norm_label_name_outlook, norm_label_color_outlook as normalize_label_color_outlook

# Re-export for backwards compatibility
_norm_label_name_outlook = norm_label_name_outlook


def normalize_labels_for_outlook(labels: list[dict[str, Any]], name_mode: str = "join-dash") -> list[dict[str, Any]]:
    seen = set()
    out: list[dict[str, Any]] = []
    for lbl in labels or []:
        if not isinstance(lbl, dict):
            continue
        name = _norm_label_name_outlook(lbl.get("name", ""), name_mode)
        if not name or name in seen:
            continue
        seen.add(name)
        entry: dict[str, Any] = {"name": name}
        c = normalize_label_color_outlook(lbl.get("color"))
        if c:
            entry["color"] = c
        out.append(entry)
    return out


def _coerce_label_list(value: object) -> list[str]:
    """Return action.add as a list of label names.

    `add` is user-authored YAML. Writing `add: work` instead of `add: [work]`
    is an easy slip, and iterating the raw value turned that single label into
    one label per CHARACTER (['w','o','r','k']) -- four bogus Outlook rules
    from a missing pair of brackets. A scalar int raised TypeError outright.
    Both are now treated as a one-element list.

    A mapping (`add: {work: true}`) is malformed too -- every real spec writes
    `add` as a list of strings. It is treated as a scalar rather than iterated,
    because iterating yields its KEYS: `{work: true, urgent: false}` would
    silently become ['work', 'urgent'], inventing a label from a key the author
    switched off. One obviously-wrong label beats several plausible ones.

    bytes decode rather than stringify, so `add: !!binary` yields 'work' and
    not the repr "b'work'".
    """
    if isinstance(value, bytes):
        return _decode_label(value)
    if isinstance(value, (str, dict)) or not isinstance(value, Iterable):
        return [str(value)] if value else []
    return [x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x) for x in value if x]


def _decode_label(value: bytes) -> list[str]:
    """Decode a bytes label to text, replacing undecodable sequences."""
    return [value.decode("utf-8", "replace")] if value else []


def normalize_filter_for_outlook(spec: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(spec, dict):
        return None
    m = spec.get("match") or {}
    a = spec.get("action") or {}
    crit = {}
    for k in ("from", "to", "subject"):
        if m.get(k):
            crit[k] = str(m[k])
    act = {}
    if a.get("add"):
        act["add"] = _coerce_label_list(a["add"])
    if a.get("forward"):
        act["forward"] = str(a["forward"])
    # Outlook-only hint: move to folder by path
    if a.get("moveToFolder"):
        act["moveToFolder"] = str(a["moveToFolder"])  # path or name
    # Per-rule opt-out from the moveToFolder derived from add[] when move-to-folders
    # is enabled, so this rule's mail stays in the inbox while others still move.
    # Carried through here; stripped from the output by _strip_keep_in_inbox.
    #
    # It is a modifier on the actions above, not an action of its own, so it only
    # rides along when one of them actually carries content. Testing `act` alone is
    # not enough: `add: ["", None]` coerces to `add: []`, leaving act truthy as a
    # dict while holding no real action.
    if a.get("keepInInbox") and any(act.get(k) for k in ("add", "forward", "moveToFolder")):
        act["keepInInbox"] = True
    if not crit and not act:
        return None
    return {"match": crit, "action": act}


def normalize_filters_for_outlook(filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in filters or []:
        nf = normalize_filter_for_outlook(f)
        if nf:
            out.append(nf)
    return out
