"""
Read an existing OneDrive Excel workbook, merge in local metals summaries, and write to a new file
with polished sheets (tables, header formatting, autofit, frozen header).

Usage example:
  python -m metals.excel_merge \
    --profile outlook_personal \
    --drive-id <DRIVE_ID> --item-id <ITEM_ID> \
    --silver-csv out/metals/silver_summary.csv --silver-sheet Silver \
    --gold-csv out/metals/gold_summary.csv --gold-sheet Gold \
    --out-name Metals Summary (Merged).xlsx
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Dict, List, Optional, Tuple

from core.auth import resolve_outlook_credentials
from core.constants import DEFAULT_OUTLOOK_TOKEN_CACHE, DEFAULT_REQUEST_TIMEOUT
from mail.outlook_api import OutlookClient
from .workbook import WorkbookContext, read_csv_rows as _read_csv, write_range_to_sheet as _write_range_wb, col_letter as _col_letter  # noqa: F401


def _to_records(values: List[List[str]]) -> Tuple[List[str], List[Dict[str, str]]]:
    if not values:
        return [], []
    headers = [str(h).strip() for h in values[0]]
    recs: List[Dict[str, str]] = []
    for row in values[1:]:
        d: Dict[str, str] = {}
        for i, h in enumerate(headers):
            d[h] = str(row[i]) if i < len(row) else ""
        # Skip empty lines (no order_id)
        if any(d.get(k) for k in headers):
            recs.append(d)
    return headers, recs


def _records_to_values(headers: List[str], recs: List[Dict[str, str]]) -> List[List[str]]:
    rows: List[List[str]] = [headers]
    for r in recs:
        rows.append([str(r.get(h, "")) for h in headers])
    return rows


def _get_used_range_values(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> List[List[str]]:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    url = f"{base}/worksheets('{sheet}')/usedRange(valuesOnly=true)?$select=values"
    r = requests.get(url, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    if r.status_code >= 400:
        # If sheet doesn't exist, return empty
        return []
    data = r.json() or {}
    return data.get("values") or []


def _poll_copy_monitor(client: OutlookClient, loc: str, drive_id: str) -> Tuple[str, str]:
    """Poll a copy monitor URL until completion. Returns (drive_id, item_id)."""
    import requests  # type: ignore
    for _ in range(60):
        st = requests.get(loc, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
        if st.get("status") in ("succeeded", "completed"):
            rid = st.get("resourceId")
            if rid:
                return drive_id, rid
            rloc = st.get("resourceLocation")
            if rloc:
                item = requests.get(rloc, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
                return drive_id, item.get("id")
        time.sleep(1.5)
    raise RuntimeError("Timed out waiting for copy to complete")


def _copy_item(client: OutlookClient, drive_id: str, item_id: str, new_name: str) -> Tuple[str, str]:
    """Copy the source drive item to the same parent with a new name.
    Returns (new_drive_id, new_item_id)."""
    import requests  # type: ignore
    meta = requests.get(f"{client.GRAPH}/drives/{drive_id}/items/{item_id}", headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
    parent_id = ((meta or {}).get("parentReference") or {}).get("id")
    body = {"name": new_name}
    if parent_id:
        body["parentReference"] = {"id": parent_id}
    copy_url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/copy"
    resp = requests.post(copy_url, headers=client._headers(), data=json.dumps(body), timeout=DEFAULT_REQUEST_TIMEOUT)
    if resp.status_code not in (202, 200):
        raise RuntimeError(f"Copy failed: {resp.status_code} {resp.text}")
    loc = resp.headers.get("Location") or resp.headers.get("Operation-Location")
    if not loc:
        try:
            item = resp.json()
            return drive_id, item.get("id")
        except Exception:
            raise RuntimeError("Copy returned no monitor location and no body")
    return _poll_copy_monitor(client, loc, drive_id)


def _ensure_sheet(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> None:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Try to add; if exists, just continue
    add_url = f"{base}/worksheets/add"
    requests.post(add_url, headers=client._headers(), data=json.dumps({"name": sheet}), timeout=DEFAULT_REQUEST_TIMEOUT)


def _write_sheet(client: OutlookClient, drive_id: str, item_id: str, sheet: str, values: List[List[str]]) -> None:
    """Write values to a workbook sheet with table styling, autofit, and frozen header."""
    wb = WorkbookContext(client, drive_id, item_id)
    _write_range_wb(wb, sheet, values)


def _merge_norm(d: Dict[str, str]) -> Dict[str, str]:
    return {str(k).strip(): str(v) for k, v in d.items()}


def _merge_key(r: Dict[str, str]) -> Tuple[str, str]:
    return (r.get("order_id", ""), r.get("vendor", ""))


_MERGE_CORE_FIELDS = ("date", "order_id", "vendor", "total_oz", "cost_per_oz")


def _merge_update(base: Dict[str, str], r: Dict[str, str]) -> None:
    for fld in _MERGE_CORE_FIELDS:
        if r.get(fld):
            base[fld] = r[fld]
    for fld, val in r.items():
        if fld not in base or not base[fld]:
            base[fld] = val


def _merge(existing: List[Dict[str, str]], new: List[Dict[str, str]]) -> List[Dict[str, str]]:
    ex = [_merge_norm(r) for r in existing]
    nw = [_merge_norm(r) for r in new]
    merged: Dict[Tuple[str, str], Dict[str, str]] = {}
    for r in ex:
        merged[_merge_key(r)] = dict(r)
    for r in nw:
        k = _merge_key(r)
        if k in merged:
            _merge_update(merged[k], r)
        else:
            merged[k] = dict(r)
    out = list(merged.values())
    out.sort(key=lambda d: (d.get("date", ""), d.get("order_id", "")))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Merge metals summaries into an Excel workbook and save as a new file")
    p.add_argument("--profile", default="outlook_personal")
    p.add_argument("--drive-id", required=True)
    p.add_argument("--item-id", required=True)
    p.add_argument("--silver-csv", required=True)
    p.add_argument("--silver-sheet", default="Silver")
    p.add_argument("--gold-csv", required=True)
    p.add_argument("--gold-sheet", default="Gold")
    p.add_argument("--out-name", default="Metals Summary (Merged).xlsx")
    args = p.parse_args(argv)

    client_id, tenant, token = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token = token or DEFAULT_OUTLOOK_TOKEN_CACHE
    if not client_id:
        raise SystemExit("No Outlook client_id configured; set it in credentials.ini under [mail.<profile>]")

    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir=".cache")
    client.authenticate()

    drive_id = getattr(args, "drive_id")
    item_id = getattr(args, "item_id")

    # Read existing workbook sheets
    vals_s_existing = _get_used_range_values(client, drive_id, item_id, getattr(args, "silver_sheet"))
    vals_g_existing = _get_used_range_values(client, drive_id, item_id, getattr(args, "gold_sheet"))
    _, rs = _to_records(vals_s_existing)
    _, rg = _to_records(vals_g_existing)

    # Read local CSVs
    vs_new = _read_csv(getattr(args, "silver_csv"))
    vg_new = _read_csv(getattr(args, "gold_csv"))
    _, rsn = _to_records(vs_new)
    _, rgn = _to_records(vg_new)

    # Merge
    s_merged = _merge(rs, rsn)
    g_merged = _merge(rg, rgn)
    # Decide headers to write (union of known headers, kept ordered with defaults first)
    base_s = ["date", "order_id", "vendor", "total_oz", "cost_per_oz"]
    base_g = ["date", "order_id", "vendor", "total_oz", "cost_per_oz"]
    def union_headers(base: List[str], recs: List[Dict[str, str]]) -> List[str]:
        seen = set(base)
        out = list(base)
        for r in recs:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    out.append(k)
        return out
    hs_final = union_headers(base_s, s_merged)
    hg_final = union_headers(base_g, g_merged)

    vals_s_final = _records_to_values(hs_final, s_merged)
    vals_g_final = _records_to_values(hg_final, g_merged)

    # Copy workbook to a new file
    new_drive_id, new_item_id = _copy_item(client, drive_id, item_id, getattr(args, "out_name"))

    # Ensure sheets exist
    sname = getattr(args, "silver_sheet")
    gname = getattr(args, "gold_sheet")
    _ensure_sheet(client, new_drive_id, new_item_id, sname)
    _ensure_sheet(client, new_drive_id, new_item_id, gname)

    # Write merged sheets with formatting
    _write_sheet(client, new_drive_id, new_item_id, sname, vals_s_final)
    _write_sheet(client, new_drive_id, new_item_id, gname, vals_g_final)
    print("merged workbook:", new_drive_id, new_item_id)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
