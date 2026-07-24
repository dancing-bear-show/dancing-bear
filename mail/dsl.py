from __future__ import annotations


from .outlook.helpers import norm_label_name_outlook, norm_label_color_outlook as normalize_label_color_outlook

# Re-export for backwards compatibility
_norm_label_name_outlook = norm_label_name_outlook


def normalize_labels_for_outlook(labels: list[dict], name_mode: str = "join-dash") -> list[dict]:
    seen = set()
    out: list[dict] = []
    for lbl in labels or []:
        if not isinstance(lbl, dict):
            continue
        name = _norm_label_name_outlook(lbl.get("name", ""), name_mode)
        if not name or name in seen:
            continue
        seen.add(name)
        entry: dict = {"name": name}
        c = normalize_label_color_outlook(lbl.get("color"))
        if c:
            entry["color"] = c
        out.append(entry)
    return out


def normalize_filter_for_outlook(spec: dict) -> dict | None:
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
        act["add"] = [str(x) for x in a["add"] if x]
    if a.get("forward"):
        act["forward"] = str(a["forward"])
    # Outlook-only hint: move to folder by path
    if a.get("moveToFolder"):
        act["moveToFolder"] = str(a["moveToFolder"])  # path or name
    if not crit and not act:
        return None
    return {"match": crit, "action": act}


def normalize_filters_for_outlook(filters: list[dict]) -> list[dict]:
    out: list[dict] = []
    for f in filters or []:
        nf = normalize_filter_for_outlook(f)
        if nf:
            out.append(nf)
    return out
