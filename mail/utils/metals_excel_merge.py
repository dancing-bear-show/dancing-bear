from __future__ import annotations

"""
Read an existing OneDrive Excel workbook, merge in local metals summaries, and write to a new file
with polished sheets (tables, header formatting, autofit, frozen header).

Usage example:
  python -m mail.utils.metals_excel_merge \
    --profile outlook_personal \
    --drive-id <DRIVE_ID> --item-id <ITEM_ID> \
    --silver-csv out/metals/silver_summary.csv --silver-sheet Silver \
    --gold-csv out/metals/gold_summary.csv --gold-sheet Gold \
    --out-name Metals Summary (Merged).xlsx
"""

import argparse
import csv
import json
import time
from typing import Dict, List, Optional, Tuple

from core.auth import resolve_outlook_credentials
from ..outlook_api import OutlookClient


def _col_letter(idx: int) -> str:
    s = ""
    n = idx
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_csv(path: str) -> List[List[str]]:
    out: List[List[str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        for row in r:
            out.append(list(row))
    return out


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
    r = requests.get(url, headers=client._headers())
    if r.status_code >= 400:
        # If sheet doesn't exist, return empty
        return []
    data = r.json() or {}
    return data.get("values") or []


def _copy_item(client: OutlookClient, drive_id: str, item_id: str, new_name: str) -> Tuple[str, str]:
    """Copy the source drive item to the same parent with a new name.
    Returns (new_drive_id, new_item_id)."""
    import requests  # type: ignore
    # Discover parent
    meta = requests.get(f"{client.GRAPH}/drives/{drive_id}/items/{item_id}", headers=client._headers()).json()
    parent = ((meta or {}).get("parentReference") or {})
    parent_id = parent.get("id")
    body = {"name": new_name}
    if parent_id:
        body["parentReference"] = {"id": parent_id}
    copy_url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/copy"
    resp = requests.post(copy_url, headers=client._headers(), data=json.dumps(body))
    if resp.status_code not in (202, 200):
        raise RuntimeError(f"Copy failed: {resp.status_code} {resp.text}")
    # Poll the monitor URL until finished
    loc = resp.headers.get("Location") or resp.headers.get("Operation-Location")
    if not loc:
        # Some tenants may return the item straight away
        try:
            item = resp.json()
            return drive_id, item.get("id")
        except Exception:
            raise RuntimeError("Copy returned no monitor location and no body")
    for _ in range(60):
        st = requests.get(loc, headers=client._headers()).json()
        # When complete, final resource location is in 'resourceId' or 'resourceLocation'
        if st.get("status") in ("succeeded", "completed"):
            rid = st.get("resourceId")
            if rid:
                return drive_id, rid
            rloc = st.get("resourceLocation")
            if rloc:
                # GET the item to fetch id
                item = requests.get(rloc, headers=client._headers()).json()
                return drive_id, item.get("id")
        time.sleep(1.5)
    raise RuntimeError("Timed out waiting for copy to complete")


def _ensure_sheet(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> None:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Try to add; if exists, just continue
    add_url = f"{base}/worksheets/add"
    requests.post(add_url, headers=client._headers(), data=json.dumps({"name": sheet}))


def _write_sheet(client: OutlookClient, drive_id: str, item_id: str, sheet: str, values: List[List[str]]) -> None:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Clear a generous range
    requests.post(
        f"{base}/worksheets('{sheet}')/range(address='A1:Z10000')/clear",
        headers=client._headers(),
        data=json.dumps({"applyTo": "contents"}),
    )
    if not values:
        return
    rows = len(values)
    cols = max(len(r) for r in values)
    end_col = _col_letter(cols)
    addr = f"A1:{end_col}{rows}"
    url = f"{base}/worksheets('{sheet}')/range(address='{addr}')"
    r = requests.patch(url, headers=client._headers(), data=json.dumps({"values": values}))
    if r.status_code >= 400:
        raise RuntimeError(f"Failed writing sheet {sheet}: {r.status_code} {r.text}")

    # Spiff it up: convert to table, format, autofit, freeze header
    # Add table
    tadd = requests.post(
        f"{base}/tables/add",
        headers=client._headers(),
        data=json.dumps({"address": f"{sheet}!{addr}", "hasHeaders": True}),
    )
    tid = None
    try:
        tid = (tadd.json() or {}).get("id")
    except Exception:
        tid = None
    if tid:
        # Apply a table style
        requests.patch(
            f"{base}/tables/{tid}",
            headers=client._headers(),
            data=json.dumps({"style": "TableStyleMedium2"}),
        )
    # Autofit columns
    requests.post(
        f"{base}/worksheets('{sheet}')/range(address='{sheet}!A:{end_col}')/format/autofitColumns",
        headers=client._headers(),
    )
    # Freeze header row
    requests.post(
        f"{base}/worksheets('{sheet}')/freezePanes/freeze",
        headers=client._headers(),
        data=json.dumps({"top": 1, "left": 0}),
    )


def _merge(existing: List[Dict[str, str]], new: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Normalize keys
    def norm(d: Dict[str, str]) -> Dict[str, str]:
        return {str(k).strip(): str(v) for k, v in d.items()}

    ex = [norm(r) for r in existing]
    nw = [norm(r) for r in new]
    # Union headers implied by keys; we'll reconcile later in _records_to_values
    # Map by composite key (order_id + vendor) when available; fallback to order_id
    def key_of(r: Dict[str, str]) -> Tuple[str, str]:
        return (r.get("order_id", ""), r.get("vendor", ""))

    merged: Dict[Tuple[str, str], Dict[str, str]] = {}
    for r in ex:
        merged[key_of(r)] = dict(r)
    for r in nw:
        k = key_of(r)
        if k in merged:
            base = merged[k]
            # Prefer new data for core fields; preserve any extra columns from existing
            for fld in ("date", "order_id", "vendor", "total_oz", "cost_per_oz"):
                if r.get(fld):
                    base[fld] = r[fld]
            # Keep any additional fields from new
            for fld, val in r.items():
                if fld not in base or not base[fld]:
                    base[fld] = val
        else:
            merged[k] = dict(r)
    # Sort by date, then order_id
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
    token = token or ".cache/.msal_token.json"
    if not client_id:
        raise SystemExit("No Outlook client_id configured; set it in credentials.ini under [mail.<profile>]")

    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir=".cache")
    client.authenticate()

    drive_id = getattr(args, "drive_id")
    item_id = getattr(args, "item_id")

    # Read existing workbook sheets
    vals_s_existing = _get_used_range_values(client, drive_id, item_id, getattr(args, "silver_sheet"))
    vals_g_existing = _get_used_range_values(client, drive_id, item_id, getattr(args, "gold_sheet"))
    hs, rs = _to_records(vals_s_existing)
    hg, rg = _to_records(vals_g_existing)

    # Read local CSVs
    vs_new = _read_csv(getattr(args, "silver_csv"))
    vg_new = _read_csv(getattr(args, "gold_csv"))
    hsn, rsn = _to_records(vs_new)
    hgn, rgn = _to_records(vg_new)

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
                    seen.add(k); out.append(k)
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
