"""I/O helpers for Excel workbook operations (read, merge, async polling)."""
from __future__ import annotations

import csv
import json
from typing import Dict, List, Optional, Tuple

from core.constants import DEFAULT_REQUEST_TIMEOUT
from core.outlook import OutlookClient

from .workbook import WorkbookContext


def _read_csv(path: str, metal: Optional[str] = None) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            d = {k: (row.get(k) or "").strip() for k in r.fieldnames or []}
            if metal:
                d["metal"] = metal
            out.append(d)
    return out


def _list_worksheets(wb: WorkbookContext) -> List[str]:
    import requests  # type: ignore
    url = f"{wb.base_url}/worksheets?$select=name"
    r = requests.get(url, headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json() or {}
    return [w.get("name", "") for w in (data.get("value") or []) if w.get("name")]


def _get_used_range_values(wb: WorkbookContext, sheet: str) -> List[List[str]]:
    import requests  # type: ignore
    url = f"{wb.sheet_url(sheet)}/usedRange(valuesOnly=true)?$select=values"
    r = requests.get(url, headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    if r.status_code >= 400:
        return []
    data = r.json() or {}
    return data.get("values") or []


def _row_to_record(
    row: List[str], headers: List[str], assumed_metal: Optional[str]
) -> Optional[Dict[str, str]]:
    """Zip a raw row against headers into a record dict, or None if the row is entirely blank."""
    d: Dict[str, str] = {h: (str(row[i]) if i < len(row) else "") for i, h in enumerate(headers)}
    if assumed_metal and not d.get("metal"):
        d["metal"] = assumed_metal
    if not any(d.get(k) for k in headers):
        return None
    return d


def _to_records(
    values: List[List[str]], assumed_metal: Optional[str] = None
) -> Tuple[List[str], List[Dict[str, str]]]:
    if not values:
        return [], []
    headers = [str(h).strip() for h in values[0]]
    recs: List[Dict[str, str]] = []
    for row in values[1:]:
        rec = _row_to_record(row, headers, assumed_metal)
        if rec is not None:
            recs.append(rec)
    return headers, recs


def _norm_row(d: Dict[str, str]) -> Dict[str, str]:
    return {str(k).strip(): str(v) for k, v in d.items()}


def _merge_all_key(r: Dict[str, str]) -> Tuple[str, str, str]:
    return (r.get("order_id", ""), r.get("vendor", ""), (r.get("metal") or "").lower())


_CORE_FIELDS = ("date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz")


def _merge_all_update(base: Dict[str, str], r: Dict[str, str]) -> None:
    for fld in _CORE_FIELDS:
        if r.get(fld):
            base[fld] = r[fld]
    for fld, val in r.items():
        if fld not in base or not base[fld]:
            base[fld] = val


def _merge_all(
    existing: List[Dict[str, str]], new: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    ex = [_norm_row(r) for r in existing]
    nw = [_norm_row(r) for r in new]
    merged: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for r in ex:
        merged[_merge_all_key(r)] = dict(r)
    for r in nw:
        k = _merge_all_key(r)
        if k in merged:
            _merge_all_update(merged[k], r)
        else:
            merged[k] = dict(r)
    out = list(merged.values())
    out.sort(key=lambda d: (d.get("date", ""), d.get("order_id", ""), d.get("metal", "")))
    return out


def _resolve_completed_operation(client: OutlookClient, st: Dict) -> Optional[str]:
    """Extract a resource ID from a completed async-operation status payload, if resolvable."""
    import requests  # type: ignore

    if st.get("status") not in ("succeeded", "completed"):
        return None
    rid = st.get("resourceId")
    if rid:
        return rid
    rloc = st.get("resourceLocation")
    if not rloc:
        return None
    it = requests.get(rloc, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
    return it.get("id")


def _poll_async_operation(
    client: OutlookClient, location: str, max_attempts: int = 60, delay: float = 1.5
) -> str:
    """Poll an async Graph operation until completion, return resource ID."""
    import requests  # type: ignore
    import time

    for _ in range(max_attempts):
        st = requests.get(location, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
        resolved = _resolve_completed_operation(client, st)
        if resolved:
            return resolved
        time.sleep(delay)
    raise RuntimeError("Timed out waiting for async operation")


def _ensure_sheet(wb: WorkbookContext, sheet: str) -> Dict[str, str]:
    import requests
    import time  # type: ignore

    r = requests.get(wb.sheet_url(sheet), headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    if r.status_code < 300:
        return r.json() or {}

    # Add if missing, with simple retries for transient 5xx
    for attempt in range(4):
        rr = requests.post(
            f"{wb.base_url}/worksheets/add",
            headers=wb.headers(),
            data=json.dumps({"name": sheet}),
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )
        if rr.status_code < 300:
            return rr.json() or {}
        if rr.status_code >= 500:
            time.sleep(2 + attempt)
            continue
        rr.raise_for_status()
    rr.raise_for_status()
    return {}


def _set_sheet_position(wb: WorkbookContext, sheet: str, position: int) -> None:
    import requests  # type: ignore
    requests.patch(
        wb.sheet_url(sheet),
        headers=wb.headers(),
        data=json.dumps({"position": int(position)}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )


def _set_sheet_visibility(wb: WorkbookContext, sheet: str, visible: bool) -> None:
    import requests  # type: ignore
    vis = "Visible" if visible else "Hidden"
    requests.patch(
        wb.sheet_url(sheet),
        headers=wb.headers(),
        data=json.dumps({"visibility": vis}),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )


def _to_values_all(recs: List[Dict[str, str]]) -> List[List[str]]:
    headers = ["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"]
    rows: List[List[str]] = [headers]
    for r in recs:
        rows.append([
            r.get("date", ""),
            r.get("order_id", ""),
            r.get("vendor", ""),
            r.get("metal", ""),
            str(r.get("total_oz", "")),
            str(r.get("cost_per_oz", "")),
        ])
    return rows


def _infer_metal_from_sheet_name(name: str) -> Optional[str]:
    """Infer the assumed metal ('silver'/'gold') from a worksheet's name, or None if ambiguous."""
    low = name.lower()
    if "silver" in low:
        return "silver"
    if "gold" in low:
        return "gold"
    return None


def _read_existing_workbook_recs(wb: WorkbookContext) -> List[Dict[str, str]]:
    """Read all sheets from workbook and consolidate records that match our schema."""
    sheet_names = _list_worksheets(wb)
    existing_all: List[Dict[str, str]] = []
    for name in sheet_names:
        vals = _get_used_range_values(wb, name)
        if not vals:
            continue
        assumed_metal = _infer_metal_from_sheet_name(name)
        _hdrs, recs = _to_records(vals, assumed_metal=assumed_metal)
        if any(r.get("order_id") or r.get("total_oz") for r in recs):
            existing_all.extend(recs)
    return existing_all
