"""
Create a single consolidated 'All' data sheet (gold + silver) and a 'Summary' sheet with
aggregations and charts, based on an existing OneDrive Excel workbook. The tool reads the
existing workbook, merges with local summaries, and writes to a new file.

Usage:
  python -m mail.utils.metals_excel_all \
    --profile outlook_personal \
    --drive-id <DRIVE_ID> --item-id <ITEM_ID> \
    --silver-csv out/metals/silver_summary.csv \
    --gold-csv out/metals/gold_summary.csv \
    --all-sheet All --summary-sheet Summary \
    --out-name "Metals Summary (Merged).xlsx"
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from core.auth import resolve_outlook_credentials
from mail.outlook_api import OutlookClient


def _col_letter(idx: int) -> str:
    s = ""
    n = idx
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


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


def _list_worksheets(client: OutlookClient, drive_id: str, item_id: str) -> List[str]:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets?$select=name"
    r = requests.get(url, headers=client._headers())  # nosec B113
    r.raise_for_status()
    data = r.json() or {}
    return [w.get("name", "") for w in (data.get("value") or []) if w.get("name")]


def _get_used_range_values(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> List[List[str]]:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/usedRange(valuesOnly=true)?$select=values"
    r = requests.get(url, headers=client._headers())  # nosec B113
    if r.status_code >= 400:
        return []
    data = r.json() or {}
    return data.get("values") or []


def _to_records(values: List[List[str]], assumed_metal: Optional[str] = None) -> Tuple[List[str], List[Dict[str, str]]]:
    if not values:
        return [], []
    headers = [str(h).strip() for h in values[0]]
    recs: List[Dict[str, str]] = []
    for row in values[1:]:
        d: Dict[str, str] = {}
        for i, h in enumerate(headers):
            d[h] = str(row[i]) if i < len(row) else ""
        if assumed_metal and not d.get("metal"):
            d["metal"] = assumed_metal
        if any(d.get(k) for k in headers):
            recs.append(d)
    return headers, recs


def _merge_all(existing: List[Dict[str, str]], new: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def norm(d: Dict[str, str]) -> Dict[str, str]:
        return {str(k).strip(): str(v) for k, v in d.items()}
    ex = [norm(r) for r in existing]
    nw = [norm(r) for r in new]
    def key_of(r: Dict[str, str]) -> Tuple[str, str, str]:
        return (r.get("order_id", ""), r.get("vendor", ""), (r.get("metal") or "").lower())
    merged: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for r in ex:
        merged[key_of(r)] = dict(r)
    for r in nw:
        k = key_of(r)
        if k in merged:
            base = merged[k]
            for fld in ("date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"):
                if r.get(fld):
                    base[fld] = r[fld]
            # Retain any extra fields
            for fld, val in r.items():
                if fld not in base or not base[fld]:
                    base[fld] = val
        else:
            merged[k] = dict(r)
    out = list(merged.values())
    out.sort(key=lambda d: (d.get("date", ""), d.get("order_id", ""), d.get("metal", "")))
    return out


def _copy_item(client: OutlookClient, drive_id: str, item_id: str, new_name: str) -> Tuple[str, str]:
    import requests  # type: ignore
    meta = requests.get(f"{client.GRAPH}/drives/{drive_id}/items/{item_id}", headers=client._headers()).json()  # nosec B113
    parent = ((meta or {}).get("parentReference") or {})
    parent_id = parent.get("id")
    body = {"name": new_name}
    if parent_id:
        body["parentReference"] = {"id": parent_id}
    copy_url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/copy"
    resp = requests.post(copy_url, headers=client._headers(), data=json.dumps(body))  # nosec B113
    if resp.status_code not in (202, 200):
        raise RuntimeError(f"Copy failed: {resp.status_code} {resp.text}")
    loc = resp.headers.get("Location") or resp.headers.get("Operation-Location")
    if not loc:
        try:
            it = resp.json(); return drive_id, it.get("id")
        except Exception:
            raise RuntimeError("Copy returned no body and no monitor location")
    for _ in range(60):
        st = requests.get(loc, headers=client._headers()).json()  # nosec B113
        if st.get("status") in ("succeeded", "completed"):
            rid = st.get("resourceId")
            if rid:
                return drive_id, rid
            rloc = st.get("resourceLocation")
            if rloc:
                it = requests.get(rloc, headers=client._headers()).json()  # nosec B113
                return drive_id, it.get("id")
        import time as _t; _t.sleep(1.5)
    raise RuntimeError("Timed out waiting for copy")


def _ensure_sheet(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> Dict[str, str]:
    import requests
    import time  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Try get by name
    r = requests.get(f"{base}/worksheets('{sheet}')", headers=client._headers())  # nosec B113
    if r.status_code < 300:
        return r.json() or {}
    # Add if missing, with simple retries for transient 5xx
    for attempt in range(4):
        rr = requests.post(f"{base}/worksheets/add", headers=client._headers(), data=json.dumps({"name": sheet}))  # nosec B113
        if rr.status_code < 300:
            return rr.json() or {}
        if rr.status_code >= 500:
            time.sleep(2 + attempt)
            continue
        rr.raise_for_status()
    rr.raise_for_status()
    return {}


def _write_range(client: OutlookClient, drive_id: str, item_id: str, sheet: str, values: List[List[str]]) -> None:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Clear
    requests.post(  # nosec B113
        f"{base}/worksheets('{sheet}')/range(address='A1:Z100000')/clear",
        headers=client._headers(),
        data=json.dumps({"applyTo": "contents"}),
    )
    if not values:
        return
    rows = len(values)
    cols = max(len(r) for r in values)
    # Pad ragged rows so Graph range write is rectangular
    padded = []
    for r in values:
        if len(r) < cols:
            r = r + [""] * (cols - len(r))
        padded.append(r)
    end_col = _col_letter(cols)
    addr = f"A1:{end_col}{rows}"
    r = requests.patch(  # nosec B113
        f"{base}/worksheets('{sheet}')/range(address='{addr}')",
        headers=client._headers(),
        data=json.dumps({"values": padded}),
    )
    r.raise_for_status()

    # Make a table
    tadd = requests.post(  # nosec B113
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
        requests.patch(  # nosec B113
            f"{base}/tables/{tid}",
            headers=client._headers(),
            data=json.dumps({"style": "TableStyleMedium2"}),
        )
    # Autofit
    requests.post(  # nosec B113
        f"{base}/worksheets('{sheet}')/range(address='{sheet}!A:{end_col}')/format/autofitColumns",
        headers=client._headers(),
    )
    # Freeze header
    requests.post(  # nosec B113
        f"{base}/worksheets('{sheet}')/freezePanes/freeze",
        headers=client._headers(),
        data=json.dumps({"top": 1, "left": 0}),
    )


def _add_chart(client: OutlookClient, drive_id: str, item_id: str, sheet: str, chart_type: str, source_addr: str, left: int = 400, top: int = 10, width: int = 600, height: int = 360) -> None:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/charts/add"
    body = {"type": chart_type, "sourceData": f"'{sheet}'!{source_addr}", "seriesBy": "Auto"}
    r = requests.post(base, headers=client._headers(), data=json.dumps(body))  # nosec B113
    if r.status_code >= 400:
        return
    try:
        cid = (r.json() or {}).get("id")
    except Exception:
        cid = None
    if cid:
        # Position the chart (optional best-effort)
        requests.patch(  # nosec B113
            f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/charts('{cid}')",
            headers=client._headers(),
            data=json.dumps({"top": top, "left": left, "width": width, "height": height}),
        )


def _to_values_all(recs: List[Dict[str, str]]) -> List[List[str]]:
    headers = ["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"]
    rows: List[List[str]] = [headers]
    for r in recs:
        rows.append([r.get("date", ""), r.get("order_id", ""), r.get("vendor", ""), r.get("metal", ""), str(r.get("total_oz", "")), str(r.get("cost_per_oz", ""))])
    return rows

def _set_sheet_position(client: OutlookClient, drive_id: str, item_id: str, sheet: str, position: int) -> None:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')"
    requests.patch(url, headers=client._headers(), data=json.dumps({"position": int(position)}))  # nosec B113

def _set_sheet_visibility(client: OutlookClient, drive_id: str, item_id: str, sheet: str, visible: bool) -> None:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')"
    vis = "Visible" if visible else "Hidden"
    requests.patch(url, headers=client._headers(), data=json.dumps({"visibility": vis}))  # nosec B113

def _write_filter_view(client: OutlookClient, drive_id: str, item_id: str, all_sheet: str, out_sheet: str, metal: str) -> None:
    """Write a dynamic FILTER view on out_sheet that references 'all_sheet' and filters by metal."""
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Clear
    requests.post(  # nosec B113
        f"{base}/worksheets('{out_sheet}')/range(address='A1:Z100000')/clear",
        headers=client._headers(),
        data=json.dumps({"applyTo": "contents"}),
    )
    # Header row
    headers = [["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"]]
    requests.patch(  # nosec B113
        f"{base}/worksheets('{out_sheet}')/range(address='A1:F1')",
        headers=client._headers(),
        data=json.dumps({"values": headers}),
    )
    # FILTER formula spills under the header
    # =FILTER(All!A2:F100000, All!D2:D100000="gold")
    formula = f"=FILTER('{all_sheet}'!A2:F100000, '{all_sheet}'!D2:D100000=\"{metal}\")"
    requests.patch(  # nosec B113
        f"{base}/worksheets('{out_sheet}')/range(address='A2')",
        headers=client._headers(),
        data=json.dumps({"values": [[formula]]}),
    )
    # Autofit and freeze header
    requests.post(  # nosec B113
        f"{base}/worksheets('{out_sheet}')/range(address='{out_sheet}!A:F')/format/autofitColumns",
        headers=client._headers(),
    )
    requests.post(  # nosec B113
        f"{base}/worksheets('{out_sheet}')/freezePanes/freeze",
        headers=client._headers(),
        data=json.dumps({"top": 1, "left": 0}),
    )


def _build_summary_values(all_recs: List[Dict[str, str]]) -> Tuple[List[List[str]], Dict[str, str]]:
    # Aggregations
    by_metal = defaultdict(lambda: {"oz": 0.0, "cost": 0.0})
    by_vendor = defaultdict(lambda: {"oz": 0.0, "cost": 0.0})
    by_month_metal = defaultdict(lambda: {"gold": {"oz": 0.0, "cost": 0.0}, "silver": {"oz": 0.0, "cost": 0.0}})
    for r in all_recs:
        try:
            oz = float(r.get("total_oz", 0) or 0)
            cpo = float(r.get("cost_per_oz", 0) or 0)
        except Exception:
            oz = 0.0; cpo = 0.0
        metal = (r.get("metal") or "").lower()
        vendor = r.get("vendor") or ""
        date = r.get("date") or ""
        month = date[:7] if len(date) >= 7 else ""
        if oz > 0 and cpo > 0:
            by_metal[metal]["oz"] += oz
            by_metal[metal]["cost"] += oz * cpo
            by_vendor[vendor]["oz"] += oz
            by_vendor[vendor]["cost"] += oz * cpo
            if month:
                by_month_metal[month][metal]["oz"] += oz
                by_month_metal[month][metal]["cost"] += oz * cpo

    # Build blocks
    blocks: List[List[List[str]]] = []
    # 1) Totals by Metal
    bm_rows = [["Metal", "Total Ounces", "Avg Cost/Oz"]]
    for metal in ("gold", "silver"):
        if metal in by_metal:
            oz = by_metal[metal]["oz"]
            avg = (by_metal[metal]["cost"] / oz) if oz else 0.0
            bm_rows.append([metal, f"{oz:.2f}", f"{avg:.2f}"])
    blocks.append(bm_rows)
    # 2) Totals by Vendor
    bv_rows = [["Vendor", "Total Ounces", "Avg Cost/Oz"]]
    for vendor, d in by_vendor.items():
        oz = d["oz"]; avg = (d["cost"] / oz) if oz else 0.0
        bv_rows.append([vendor, f"{oz:.2f}", f"{avg:.2f}"])
    blocks.append(bv_rows)
    # 3) Monthly Avg Cost by Metal
    mm_rows = [["Month", "Gold Avg", "Silver Avg"]]
    for month in sorted(by_month_metal.keys()):
        g = by_month_metal[month]["gold"]; s = by_month_metal[month]["silver"]
        gavg = (g["cost"] / g["oz"]) if g["oz"] else 0.0
        savg = (s["cost"] / s["oz"]) if s["oz"] else 0.0
        mm_rows.append([month, f"{gavg:.2f}", f"{savg:.2f}"])
    blocks.append(mm_rows)
    # 4) Monthly Ounces by Metal
    mo_rows = [["Month", "Gold Ounces", "Silver Ounces"]]
    for month in sorted(by_month_metal.keys()):
        g = by_month_metal[month]["gold"]; s = by_month_metal[month]["silver"]
        mo_rows.append([month, f"{g['oz']:.2f}", f"{s['oz']:.2f}"])
    blocks.append(mo_rows)

    # Stitch into a single 2-column separated layout on Summary
    values: List[List[str]] = []
    anchors: Dict[str, str] = {}
    row_cursor = 1
    for idx, block in enumerate(blocks):
        # Leave a title row
        title = [
            "Totals by Metal",
            "Totals by Vendor",
            "Monthly Avg Cost by Metal",
            "Monthly Ounces by Metal",
        ][idx]
        values.append([title])
        row_cursor += 1
        start_row = row_cursor
        for r in block:
            values.append(r)
            row_cursor += 1
        end_row = row_cursor - 1
        # Reserve a blank row between sections
        values.append([""])
        row_cursor += 1
        # Record range anchors for charts (skip the header row inside block)
        start = f"A{start_row}:" + f"{_col_letter(len(block[0]))}{end_row}"
        anchors[title] = start
    return values, anchors


def _fetch_yahoo_series(symbol: str, start_date: str, end_date: str) -> Dict[str, float]:
    """Fetch daily closes from Yahoo chart API for the given symbol between dates (YYYY-MM-DD).

    Returns dict of ISO date -> close price. Forward-fills gaps and back-fills
    the initial window to the first available value so a continuous series is produced.
    """
    import requests  # type: ignore
    from datetime import datetime, timezone

    def to_unix(d: str) -> int:
        dt = datetime.fromisoformat(d)
        return int(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp())

    p1 = to_unix(start_date)
    # Add one day to include end
    p2 = to_unix(end_date) + 24 * 3600
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={p1}&period2={p2}&interval=1d"
    r = requests.get(url, timeout=20)  # nosec B113
    try:
        data = r.json() or {}
    except Exception:
        data = {}
    out: Dict[str, float] = {}
    try:
        res = ((data.get("chart") or {}).get("result") or [])[0]
        ts = res.get("timestamp", [])
        cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close", [])
        from datetime import datetime, timezone
        for i, t in enumerate(ts or []):
            try:
                d = datetime.fromtimestamp(int(t), tz=timezone.utc).date().isoformat()
                v = cl[i]
                if v is not None:
                    out[d] = float(v)
            except Exception:
                continue
    except Exception:
        return out
    # Forward-fill minor gaps
    if out:
        from datetime import date, timedelta
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        d = start
        last = None
        while d <= end:
            ds = d.isoformat()
            if ds in out:
                last = out[ds]
            elif last is not None:
                out[ds] = last
            d += timedelta(days=1)
    # Forward-fill minor gaps and back-fill start
    if out:
        from datetime import date, timedelta
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        d = start
        last = None
        # If our first available point starts after `start`, remember its value for back-fill
        avail_dates = sorted(out.keys())
        first_val = out.get(avail_dates[0]) if avail_dates else None
        while d <= end:
            ds = d.isoformat()
            if ds in out:
                last = out[ds]
            elif last is not None:
                out[ds] = last
            elif first_val is not None:
                # Back-fill at the very beginning
                out[ds] = first_val
                last = first_val
            d += timedelta(days=1)
    return out


def _spot_cad_series(metal: str, start_date: str, end_date: str) -> Dict[str, float]:
    """Return a CAD-denominated spot series for metal in {gold, silver}.

    Tries native CAD pairs first (XAUCAD=X / XAGCAD=X). Falls back to USD pairs with
    FX conversion via USDCAD=X.
    """
    metal = (metal or '').lower()
    if metal not in ('gold', 'silver'):
        return {}
    sym_primary = 'XAUCAD=X' if metal == 'gold' else 'XAGCAD=X'
    primary = _fetch_yahoo_series(sym_primary, start_date, end_date)
    # Fallback path: USD * USDCAD
    sym_usd = 'XAUUSD=X' if metal == 'gold' else 'XAGUSD=X'
    usd = _fetch_yahoo_series(sym_usd, start_date, end_date)
    usdcad = _fetch_yahoo_series('USDCAD=X', start_date, end_date)
    cad_from_usd: Dict[str, float] = {}
    if usd and usdcad:
        # Element-wise product where both exist
        keys = set(usd.keys()) & set(usdcad.keys())
        for k in keys:
            try:
                cad_from_usd[k] = float(usd[k]) * float(usdcad[k])
            except Exception:
                continue
    # Compose: prefer primary when available; otherwise use converted
    if not primary and cad_from_usd:
        return cad_from_usd
    out = dict(primary)
    for k, v in cad_from_usd.items():
        if k not in out or out[k] is None:
            out[k] = v
    return out


def _build_profit_series(all_recs: List[Dict[str, str]]) -> List[List[str]]:
    """Return values for a Profit sheet with columns:
    Date, Gold_Oz, Gold_AvgCost, Gold_Spot, Gold_PnL, Silver_Oz, Silver_AvgCost, Silver_Spot, Silver_PnL, Portfolio_PnL
    """
    from datetime import date

    # Collect purchases by date
    by_date = defaultdict(lambda: {"gold": {"oz": 0.0, "cost": 0.0}, "silver": {"oz": 0.0, "cost": 0.0}})
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    for r in all_recs:
        try:
            d = (r.get("date") or "").strip()
            m = (r.get("metal") or "").lower()
            oz = float(r.get("total_oz") or 0)
            cpo = float(r.get("cost_per_oz") or 0)
        except Exception:
            continue
        if not d or m not in ("gold", "silver") or oz <= 0 or cpo <= 0:
            continue
        if (min_date is None) or d < min_date:
            min_date = d
        if (max_date is None) or d > max_date:
            max_date = d
        by_date[d][m]["oz"] += oz
        by_date[d][m]["cost"] += oz * cpo

    if not min_date or not max_date:
        return []

    # Fetch spot in CAD for date range with USD fallback
    spot_gold = _spot_cad_series('gold', min_date, max_date)
    spot_silver = _spot_cad_series('silver', min_date, max_date)

    # Walk days, compute cumulative ounces and avg cost, then PnL
    values: List[List[str]] = [[
        "date",
        "gold_oz", "gold_avg_cost", "gold_spot", "gold_pnl",
        "silver_oz", "silver_avg_cost", "silver_spot", "silver_pnl",
        "portfolio_pnl",
    ]]

    # Running inventory
    g_oz = 0.0; g_cost = 0.0
    s_oz = 0.0; s_cost = 0.0

    cur = date.fromisoformat(min_date)
    end = date.fromisoformat(max_date)
    while cur <= end:
        ds = cur.isoformat()
        # Apply any purchases on this day
        add = by_date.get(ds)
        if add:
            g_oz += add["gold"]["oz"]; g_cost += add["gold"]["cost"]
            s_oz += add["silver"]["oz"]; s_cost += add["silver"]["cost"]
        g_avg = (g_cost / g_oz) if g_oz > 0 else 0.0
        s_avg = (s_cost / s_oz) if s_oz > 0 else 0.0
        g_spot = spot_gold.get(ds)
        s_spot = spot_silver.get(ds)
        if g_spot is None and spot_gold:
            # fallback to last available <= ds
            # already filled forward; if missing at beginning, skip pnl
            g_spot = spot_gold.get(ds)
        if s_spot is None and spot_silver:
            s_spot = spot_silver.get(ds)
        g_pnl = (g_spot - g_avg) * g_oz if (g_spot and g_avg and g_oz) else 0.0
        s_pnl = (s_spot - s_avg) * s_oz if (s_spot and s_avg and s_oz) else 0.0
        port = g_pnl + s_pnl
        values.append([
            ds,
            f"{g_oz:.4f}", f"{g_avg:.2f}", f"{(g_spot or 0):.2f}", f"{g_pnl:.2f}",
            f"{s_oz:.4f}", f"{s_avg:.2f}", f"{(s_spot or 0):.2f}", f"{s_pnl:.2f}",
            f"{port:.2f}",
        ])
        cur = cur.fromordinal(cur.toordinal() + 1)
    return values


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Create single 'All' sheet + 'Summary' with charts from workbook + local summaries")
    p.add_argument("--profile", default="outlook_personal")
    p.add_argument("--drive-id", required=True)
    p.add_argument("--item-id", required=True)
    p.add_argument("--silver-csv", required=True)
    p.add_argument("--gold-csv", required=True)
    p.add_argument("--all-sheet", default="All")
    p.add_argument("--summary-sheet", default="Summary")
    p.add_argument("--out-name", default="Metals Summary (Merged).xlsx")
    args = p.parse_args(argv)

    profile = getattr(args, "profile", None)
    client_id, tenant, token = resolve_outlook_credentials(
        profile,
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token = token or ".cache/.msal_token.json"
    if not client_id:
        raise SystemExit("No Outlook client_id configured in credentials.ini")

    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir=".cache")
    client.authenticate()

    drive_id = getattr(args, "drive_id"); item_id = getattr(args, "item_id")
    # Read existing workbook sheets and consolidate to All
    sheet_names = _list_worksheets(client, drive_id, item_id)
    existing_all: List[Dict[str, str]] = []
    for name in sheet_names:
        vals = _get_used_range_values(client, drive_id, item_id, name)
        if not vals:
            continue
        assumed_metal = None
        low = name.lower()
        if "silver" in low:
            assumed_metal = "silver"
        elif "gold" in low:
            assumed_metal = "gold"
        hdrs, recs = _to_records(vals, assumed_metal=assumed_metal)
        # Only accept if it looks like our schema (has order_id or total_oz)
        if any(r.get("order_id") or r.get("total_oz") for r in recs):
            existing_all.extend(recs)

    # Read local summaries and tag metal
    local_silver = _read_csv(getattr(args, "silver_csv"), metal="silver")
    local_gold = _read_csv(getattr(args, "gold_csv"), metal="gold")
    # Normalize to expected keys
    for r in local_silver + local_gold:
        r["metal"] = (r.get("metal") or "").lower()

    all_merged = _merge_all(existing_all, local_silver + local_gold)
    # Compose 'All' values
    all_values = _to_values_all(all_merged)

    # Build summary (we will write formula-driven summary referencing All; keep computed values for future use if needed)
    summary_values, anchors = _build_summary_values(all_merged)

    # Copy workbook to new item
    new_did, new_iid = _copy_item(client, drive_id, item_id, getattr(args, "out_name"))

    # Ensure sheets
    all_name = getattr(args, "all_sheet"); sum_name = getattr(args, "summary_sheet")
    gold_name = "Gold"; silver_name = "Silver"
    _ensure_sheet(client, new_did, new_iid, all_name)
    _ensure_sheet(client, new_did, new_iid, sum_name)
    _ensure_sheet(client, new_did, new_iid, gold_name)
    _ensure_sheet(client, new_did, new_iid, silver_name)

    # Write All and Summary (formulas)
    _write_range(client, new_did, new_iid, all_name, all_values)
    # Formula-driven Summary referencing All
    sum_formulas = [
        ["Totals by Metal"],
        ["Metal", "Total Ounces", "Avg Cost/Oz"],
        [
            "gold",
            "=SUMIF('"+all_name+"'!$D$2:$D$100000,\"gold\",'"+all_name+"'!$E$2:$E$100000)",
            "=IFERROR(SUMPRODUCT(('"+all_name+"'!$D$2:$D$100000=\"gold\")*'"+all_name+"'!$E$2:$E$100000*'"+all_name+"'!$F$2:$F$100000)/SUMIF('"+all_name+"'!$D$2:$D$100000,\"gold\",'"+all_name+"'!$E$2:$E$100000),\"\")",
        ],
        [
            "silver",
            "=SUMIF('"+all_name+"'!$D$2:$D$100000,\"silver\",'"+all_name+"'!$E$2:$E$100000)",
            "=IFERROR(SUMPRODUCT(('"+all_name+"'!$D$2:$D$100000=\"silver\")*'"+all_name+"'!$E$2:$E$100000*'"+all_name+"'!$F$2:$F$100000)/SUMIF('"+all_name+"'!$D$2:$D$100000,\"silver\",'"+all_name+"'!$E$2:$E$100000),\"\")",
        ],
        [""],
        ["Totals by Vendor"],
        ["Vendor", "Total Ounces", "Avg Cost/Oz"],
        [
            "TD",
            "=SUMIF('"+all_name+"'!$C$2:$C$100000,\"TD\",'"+all_name+"'!$E$2:$E$100000)",
            "=IFERROR(SUMPRODUCT(('"+all_name+"'!$C$2:$C$100000=\"TD\")*'"+all_name+"'!$E$2:$E$100000*'"+all_name+"'!$F$2:$F$100000)/SUMIF('"+all_name+"'!$C$2:$C$100000,\"TD\",'"+all_name+"'!$E$2:$E$100000),\"\")",
        ],
        [
            "Costco",
            "=SUMIF('"+all_name+"'!$C$2:$C$100000,\"Costco\",'"+all_name+"'!$E$2:$E$100000)",
            "=IFERROR(SUMPRODUCT(('"+all_name+"'!$C$2:$C$100000=\"Costco\")*'"+all_name+"'!$E$2:$E$100000*'"+all_name+"'!$F$2:$F$100000)/SUMIF('"+all_name+"'!$C$2:$C$100000,\"Costco\",'"+all_name+"'!$E$2:$E$100000),\"\")",
        ],
    ]
    _write_range(client, new_did, new_iid, sum_name, sum_formulas)

    # Gold/Silver sheets reference All via FILTER so data lives only once
    _write_filter_view(client, new_did, new_iid, all_name, gold_name, "gold")
    _write_filter_view(client, new_did, new_iid, all_name, silver_name, "silver")

    # Add charts on summary — chart totals by metal from Summary!B3:C4
    _add_chart(client, new_did, new_iid, sum_name, "ColumnClustered", "B3:C4", left=360, top=10)

    # Create Profit sheet with time-series PnL and charts
    profit_values = _build_profit_series(all_merged)
    if profit_values:
        profit_name = "Profit"
        _ensure_sheet(client, new_did, new_iid, profit_name)
        _write_range(client, new_did, new_iid, profit_name, profit_values)
        # Chart: Portfolio PnL over time (column J)
        rows = len(profit_values)
        # Data range J2:J{rows}
        _add_chart(client, new_did, new_iid, profit_name, "Line", f"J2:J{rows}", left=10, top=10, width=700, height=360)
        # Chart: Gold vs Silver spot and avg (columns C,D and G,H) — optional separate charts
        _add_chart(client, new_did, new_iid, profit_name, "Line", f"C2:D{rows}", left=10, top=380, width=700, height=280)
        _add_chart(client, new_did, new_iid, profit_name, "Line", f"G2:H{rows}", left=10, top=680, width=700, height=280)

    # Sheet order: Summary first, then Gold, then Silver; All last and hidden
    try:
        _set_sheet_position(client, new_did, new_iid, sum_name, 0)
        _set_sheet_position(client, new_did, new_iid, gold_name, 1)
        _set_sheet_position(client, new_did, new_iid, silver_name, 2)
    except Exception:
        pass  # nosec B110 - non-critical sheet positioning
    try:
        _set_sheet_visibility(client, new_did, new_iid, all_name, False)
    except Exception:
        pass  # nosec B110 - non-critical sheet visibility

    print("created consolidated workbook:", new_did, new_iid, "(Summary, Gold, Silver; All hidden)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
