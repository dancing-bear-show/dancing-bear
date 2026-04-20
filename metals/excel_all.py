"""
Create a single consolidated 'All' data sheet (gold + silver) and a 'Summary' sheet with
aggregations and charts, based on an existing OneDrive Excel workbook. The tool reads the
existing workbook, merges with local summaries, and writes to a new file.

Usage:
  python -m metals.excel_all \
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
from core.constants import DEFAULT_OUTLOOK_TOKEN_CACHE, DEFAULT_REQUEST_TIMEOUT
from mail.outlook_api import OutlookClient
from .workbook import WorkbookContext, ChartPlacement, col_letter as _col_letter, write_range_to_sheet as _write_range, pad_rows as _pad_rows  # noqa: F401


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


def _merge_all(existing: List[Dict[str, str]], new: List[Dict[str, str]]) -> List[Dict[str, str]]:
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


def _poll_async_operation(
    client: OutlookClient, location: str, max_attempts: int = 60, delay: float = 1.5
) -> str:
    """Poll an async Graph operation until completion, return resource ID."""
    import requests  # type: ignore
    import time

    for _ in range(max_attempts):
        st = requests.get(location, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
        if st.get("status") in ("succeeded", "completed"):
            if rid := st.get("resourceId"):
                return rid
            if rloc := st.get("resourceLocation"):
                it = requests.get(rloc, headers=client._headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
                return it.get("id")
        time.sleep(delay)
    raise RuntimeError("Timed out waiting for async operation")


def _copy_item(wb: WorkbookContext, new_name: str) -> WorkbookContext:
    import requests  # type: ignore

    meta = requests.get(f"{wb.client.GRAPH}/drives/{wb.drive_id}/items/{wb.item_id}", headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).json()
    parent_id = ((meta or {}).get("parentReference") or {}).get("id")
    body = {"name": new_name}
    if parent_id:
        body["parentReference"] = {"id": parent_id}

    copy_url = f"{wb.client.GRAPH}/drives/{wb.drive_id}/items/{wb.item_id}/copy"
    resp = requests.post(copy_url, headers=wb.headers(), data=json.dumps(body), timeout=DEFAULT_REQUEST_TIMEOUT)
    if resp.status_code not in (202, 200):
        raise RuntimeError(f"Copy failed: {resp.status_code} {resp.text}")

    location = resp.headers.get("Location") or resp.headers.get("Operation-Location")
    if not location:
        try:
            new_id = resp.json().get("id")
            return WorkbookContext(wb.client, wb.drive_id, new_id)
        except Exception:
            raise RuntimeError("Copy returned no body and no monitor location")

    new_id = _poll_async_operation(wb.client, location)
    return WorkbookContext(wb.client, wb.drive_id, new_id)


def _ensure_sheet(wb: WorkbookContext, sheet: str) -> Dict[str, str]:
    import requests
    import time  # type: ignore

    r = requests.get(wb.sheet_url(sheet), headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    if r.status_code < 300:
        return r.json() or {}

    # Add if missing, with simple retries for transient 5xx
    for attempt in range(4):
        rr = requests.post(f"{wb.base_url}/worksheets/add", headers=wb.headers(), data=json.dumps({"name": sheet}), timeout=DEFAULT_REQUEST_TIMEOUT)
        if rr.status_code < 300:
            return rr.json() or {}
        if rr.status_code >= 500:
            time.sleep(2 + attempt)
            continue
        rr.raise_for_status()
    rr.raise_for_status()
    return {}




def _add_chart(
    wb: WorkbookContext,
    sheet: str,
    chart_type: str,
    source_addr: str,
    placement: Optional[ChartPlacement] = None,
) -> None:
    import requests  # type: ignore

    placement = placement or ChartPlacement()
    url = f"{wb.sheet_url(sheet)}/charts/add"
    body = {"type": chart_type, "sourceData": f"'{sheet}'!{source_addr}", "seriesBy": "Auto"}
    r = requests.post(url, headers=wb.headers(), data=json.dumps(body), timeout=DEFAULT_REQUEST_TIMEOUT)
    if r.status_code >= 400:
        return

    try:
        if cid := (r.json() or {}).get("id"):
            requests.patch(
                wb.chart_url(sheet, cid),
                headers=wb.headers(),
                data=json.dumps({"top": placement.top, "left": placement.left, "width": placement.width, "height": placement.height}),
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
    except Exception:
        pass  # nosec B110 - chart positioning is optional


def _to_values_all(recs: List[Dict[str, str]]) -> List[List[str]]:
    headers = ["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"]
    rows: List[List[str]] = [headers]
    for r in recs:
        rows.append([r.get("date", ""), r.get("order_id", ""), r.get("vendor", ""), r.get("metal", ""), str(r.get("total_oz", "")), str(r.get("cost_per_oz", ""))])
    return rows

def _set_sheet_position(wb: WorkbookContext, sheet: str, position: int) -> None:
    import requests  # type: ignore
    requests.patch(wb.sheet_url(sheet), headers=wb.headers(), data=json.dumps({"position": int(position)}), timeout=DEFAULT_REQUEST_TIMEOUT)


def _set_sheet_visibility(wb: WorkbookContext, sheet: str, visible: bool) -> None:
    import requests  # type: ignore
    vis = "Visible" if visible else "Hidden"
    requests.patch(wb.sheet_url(sheet), headers=wb.headers(), data=json.dumps({"visibility": vis}), timeout=DEFAULT_REQUEST_TIMEOUT)


def _write_filter_view(wb: WorkbookContext, all_sheet: str, out_sheet: str, metal: str) -> None:
    """Write a dynamic FILTER view on out_sheet that references 'all_sheet' and filters by metal."""
    import requests  # type: ignore

    out_url = wb.sheet_url(out_sheet)

    # Clear, write header, write FILTER formula
    requests.post(f"{out_url}/range(address='A1:Z100000')/clear", headers=wb.headers(), data=json.dumps({"applyTo": "contents"}), timeout=DEFAULT_REQUEST_TIMEOUT)
    requests.patch(f"{out_url}/range(address='A1:F1')", headers=wb.headers(), data=json.dumps({"values": [["date", "order_id", "vendor", "metal", "total_oz", "cost_per_oz"]]}), timeout=DEFAULT_REQUEST_TIMEOUT)
    formula = f"=FILTER('{all_sheet}'!A2:F100000, '{all_sheet}'!D2:D100000=\"{metal}\")"
    requests.patch(f"{out_url}/range(address='A2')", headers=wb.headers(), data=json.dumps({"values": [[formula]]}), timeout=DEFAULT_REQUEST_TIMEOUT)

    # Autofit and freeze header
    requests.post(f"{out_url}/range(address='{out_sheet}!A:F')/format/autofitColumns", headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    requests.post(f"{out_url}/freezePanes/freeze", headers=wb.headers(), data=json.dumps({"top": 1, "left": 0}), timeout=DEFAULT_REQUEST_TIMEOUT)


def _sumif_formula(sheet: str, match_col: str, match_val: str, sum_col: str) -> str:
    """Build a SUMIF formula for Excel."""
    return f"=SUMIF('{sheet}'!${match_col}$2:${match_col}$100000,\"{match_val}\",'{sheet}'!${sum_col}$2:${sum_col}$100000)"


def _avgcost_formula(sheet: str, match_col: str, match_val: str, oz_col: str, cpo_col: str) -> str:
    """Build a weighted average cost formula (SUMPRODUCT/SUMIF) for Excel."""
    return (
        f"=IFERROR(SUMPRODUCT(('{sheet}'!${match_col}$2:${match_col}$100000=\"{match_val}\")*"
        f"'{sheet}'!${oz_col}$2:${oz_col}$100000*'{sheet}'!${cpo_col}$2:${cpo_col}$100000)/"
        f"SUMIF('{sheet}'!${match_col}$2:${match_col}$100000,\"{match_val}\",'{sheet}'!${oz_col}$2:${oz_col}$100000),\"\")"
    )


def _summary_row(sheet: str, label: str, match_col: str, oz_col: str = "E", cpo_col: str = "F") -> List[str]:
    """Build a summary row with label, total oz, and avg cost formulas."""
    return [label, _sumif_formula(sheet, match_col, label, oz_col), _avgcost_formula(sheet, match_col, label, oz_col, cpo_col)]


_SUMMARY_TITLES = [
    "Totals by Metal",
    "Totals by Vendor",
    "Monthly Avg Cost by Metal",
    "Monthly Ounces by Metal",
]

AVG_COST_HDR = "Avg Cost/Oz"
TOTAL_OZ_HDR = "Total Ounces"


def _agg_rec_update(
    r: Dict[str, str],
    by_metal: dict, by_vendor: dict, by_month_metal: dict,
) -> None:
    """Update aggregation dicts with a single record."""
    try:
        oz = float(r.get("total_oz", 0) or 0)
        cpo = float(r.get("cost_per_oz", 0) or 0)
    except Exception:  # nosec B110 - skip malformed numeric fields
        return
    if oz <= 0 or cpo <= 0:
        return
    metal = (r.get("metal") or "").lower()
    vendor = r.get("vendor") or ""
    date_val = r.get("date") or ""
    month = date_val[:7] if len(date_val) >= 7 else ""
    total = oz * cpo
    by_metal[metal]["oz"] += oz
    by_metal[metal]["cost"] += total
    by_vendor[vendor]["oz"] += oz
    by_vendor[vendor]["cost"] += total
    if month:
        by_month_metal[month][metal]["oz"] += oz
        by_month_metal[month][metal]["cost"] += total


def _aggregate_summary_recs(all_recs: List[Dict[str, str]]) -> Tuple[dict, dict, dict]:
    """Aggregate records into by_metal, by_vendor, by_month_metal dicts."""
    by_metal = defaultdict(lambda: {"oz": 0.0, "cost": 0.0})
    by_vendor = defaultdict(lambda: {"oz": 0.0, "cost": 0.0})
    by_month_metal = defaultdict(lambda: {"gold": {"oz": 0.0, "cost": 0.0}, "silver": {"oz": 0.0, "cost": 0.0}})
    for r in all_recs:
        _agg_rec_update(r, by_metal, by_vendor, by_month_metal)
    return by_metal, by_vendor, by_month_metal


def _build_metal_rows(by_metal: dict) -> List[List[str]]:
    """Build totals-by-metal rows."""
    rows: List[List[str]] = [["Metal", TOTAL_OZ_HDR, AVG_COST_HDR]]
    for metal in ("gold", "silver"):
        if metal in by_metal:
            oz = by_metal[metal]["oz"]
            avg = (by_metal[metal]["cost"] / oz) if oz else 0.0
            rows.append([metal, f"{oz:.2f}", f"{avg:.2f}"])
    return rows


def _build_vendor_rows(by_vendor: dict) -> List[List[str]]:
    """Build totals-by-vendor rows."""
    rows: List[List[str]] = [["Vendor", TOTAL_OZ_HDR, AVG_COST_HDR]]
    for vendor, d in by_vendor.items():
        oz = d["oz"]
        avg = (d["cost"] / oz) if oz else 0.0
        rows.append([vendor, f"{oz:.2f}", f"{avg:.2f}"])
    return rows


def _build_monthly_avg_rows(by_month_metal: dict) -> List[List[str]]:
    """Build monthly avg cost by metal rows."""
    rows: List[List[str]] = [["Month", "Gold Avg", "Silver Avg"]]
    for month in sorted(by_month_metal.keys()):
        g = by_month_metal[month]["gold"]
        s = by_month_metal[month]["silver"]
        gavg = (g["cost"] / g["oz"]) if g["oz"] else 0.0
        savg = (s["cost"] / s["oz"]) if s["oz"] else 0.0
        rows.append([month, f"{gavg:.2f}", f"{savg:.2f}"])
    return rows


def _build_monthly_oz_rows(by_month_metal: dict) -> List[List[str]]:
    """Build monthly ounces by metal rows."""
    rows: List[List[str]] = [["Month", "Gold Ounces", "Silver Ounces"]]
    for month in sorted(by_month_metal.keys()):
        g = by_month_metal[month]["gold"]
        s = by_month_metal[month]["silver"]
        rows.append([month, f"{g['oz']:.2f}", f"{s['oz']:.2f}"])
    return rows


def _build_summary_blocks(by_metal: dict, by_vendor: dict, by_month_metal: dict) -> List[List[List[str]]]:
    """Build summary table blocks from aggregated data."""
    return [
        _build_metal_rows(by_metal),
        _build_vendor_rows(by_vendor),
        _build_monthly_avg_rows(by_month_metal),
        _build_monthly_oz_rows(by_month_metal),
    ]


def _stitch_summary_blocks(blocks: List[List[List[str]]]) -> Tuple[List[List[str]], Dict[str, str]]:
    """Stitch blocks into single layout with anchors for charts."""
    values: List[List[str]] = []
    anchors: Dict[str, str] = {}
    row_cursor = 1
    for idx, block in enumerate(blocks):
        title = _SUMMARY_TITLES[idx]
        values.append([title])
        row_cursor += 1
        start_row = row_cursor
        for r in block:
            values.append(r)
            row_cursor += 1
        end_row = row_cursor - 1
        values.append([""])
        row_cursor += 1
        anchors[title] = f"A{start_row}:{_col_letter(len(block[0]))}{end_row}"
    return values, anchors


def _build_summary_values(all_recs: List[Dict[str, str]]) -> Tuple[List[List[str]], Dict[str, str]]:
    by_metal, by_vendor, by_month_metal = _aggregate_summary_recs(all_recs)
    blocks = _build_summary_blocks(by_metal, by_vendor, by_month_metal)
    return _stitch_summary_blocks(blocks)


def _fill_date_gaps(
    series: Dict[str, float], start_date: str, end_date: str
) -> Dict[str, float]:
    """Forward-fill and back-fill gaps in a date series to produce a continuous series."""
    if not series:
        return series
    from datetime import date, timedelta

    out = dict(series)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    # Get first available value for back-fill
    avail_dates = sorted(out.keys())
    first_val = out.get(avail_dates[0]) if avail_dates else None

    d = start
    last = None
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
    r = requests.get(url, timeout=DEFAULT_REQUEST_TIMEOUT)
    try:
        data = r.json() or {}
    except Exception:
        data = {}
    out: Dict[str, float] = {}
    try:
        res = ((data.get("chart") or {}).get("result") or [])[0]
        ts = res.get("timestamp", [])
        cl = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close", [])
        for i, t in enumerate(ts or []):
            try:
                d = datetime.fromtimestamp(int(t), tz=timezone.utc).date().isoformat()
                v = cl[i]
                if v is not None:
                    out[d] = float(v)
            except Exception:  # nosec B112 - skip on error
                continue
    except Exception:
        return out
    return _fill_date_gaps(out, start_date, end_date)


def _usd_to_cad_series(usd: Dict[str, float], usdcad: Dict[str, float]) -> Dict[str, float]:
    """Multiply USD and USDCAD series element-wise to produce CAD values."""
    out: Dict[str, float] = {}
    if not usd or not usdcad:
        return out
    for k in set(usd.keys()) & set(usdcad.keys()):
        try:
            out[k] = float(usd[k]) * float(usdcad[k])
        except Exception:  # nosec B112 - skip on error
            continue
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
    sym_usd = 'XAUUSD=X' if metal == 'gold' else 'XAGUSD=X'
    usd = _fetch_yahoo_series(sym_usd, start_date, end_date)
    usdcad = _fetch_yahoo_series('USDCAD=X', start_date, end_date)
    cad_from_usd = _usd_to_cad_series(usd, usdcad)
    if not primary and cad_from_usd:
        return cad_from_usd
    out = dict(primary)
    for k, v in cad_from_usd.items():
        if k not in out or out[k] is None:
            out[k] = v
    return out


def _parse_profit_rec(r: Dict[str, str]) -> Optional[Tuple[str, str, float, float]]:
    """Parse a record into (date, metal, oz, cpo) or None if invalid."""
    try:
        d = (r.get("date") or "").strip()
        m = (r.get("metal") or "").lower()
        oz = float(r.get("total_oz") or 0)
        cpo = float(r.get("cost_per_oz") or 0)
    except Exception:  # nosec B110 - skip malformed records
        return None
    if not d or m not in ("gold", "silver") or oz <= 0 or cpo <= 0:
        return None
    return d, m, oz, cpo


def _collect_profit_by_date(all_recs: List[Dict[str, str]]) -> Tuple[dict, Optional[str], Optional[str]]:
    """Collect purchase totals by date from records. Returns (by_date, min_date, max_date)."""
    by_date = defaultdict(lambda: {"gold": {"oz": 0.0, "cost": 0.0}, "silver": {"oz": 0.0, "cost": 0.0}})
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    for r in all_recs:
        parsed = _parse_profit_rec(r)
        if parsed is None:
            continue
        d, m, oz, cpo = parsed
        if (min_date is None) or d < min_date:
            min_date = d
        if (max_date is None) or d > max_date:
            max_date = d
        by_date[d][m]["oz"] += oz
        by_date[d][m]["cost"] += oz * cpo
    return by_date, min_date, max_date


def _pnl_row(
    ds: str,
    g_oz: float, g_avg: float, g_spot: Optional[float],
    s_oz: float, s_avg: float, s_spot: Optional[float],
) -> List[str]:
    """Build a single profit/loss row for a date."""
    g_pnl = (g_spot - g_avg) * g_oz if (g_spot and g_avg and g_oz) else 0.0
    s_pnl = (s_spot - s_avg) * s_oz if (s_spot and s_avg and s_oz) else 0.0
    return [
        ds,
        f"{g_oz:.4f}", f"{g_avg:.2f}", f"{(g_spot or 0):.2f}", f"{g_pnl:.2f}",
        f"{s_oz:.4f}", f"{s_avg:.2f}", f"{(s_spot or 0):.2f}", f"{s_pnl:.2f}",
        f"{g_pnl + s_pnl:.2f}",
    ]


def _accumulate_day(
    add: Optional[dict],
    g_oz: float, g_cost: float,
    s_oz: float, s_cost: float,
) -> Tuple[float, float, float, float]:
    """Accumulate gold/silver oz and cost from a day's purchases."""
    if add:
        g_oz += add["gold"]["oz"]
        g_cost += add["gold"]["cost"]
        s_oz += add["silver"]["oz"]
        s_cost += add["silver"]["cost"]
    return g_oz, g_cost, s_oz, s_cost


def _profit_walk_days(
    by_date: dict,
    min_date: str,
    max_date: str,
    spot_gold: Dict[str, float],
    spot_silver: Dict[str, float],
) -> List[List[str]]:
    """Walk date range producing per-day PnL rows."""
    from datetime import date

    values: List[List[str]] = [[
        "date",
        "gold_oz", "gold_avg_cost", "gold_spot", "gold_pnl",
        "silver_oz", "silver_avg_cost", "silver_spot", "silver_pnl",
        "portfolio_pnl",
    ]]
    g_oz = g_cost = s_oz = s_cost = 0.0
    cur = date.fromisoformat(min_date)
    end = date.fromisoformat(max_date)
    while cur <= end:
        ds = cur.isoformat()
        g_oz, g_cost, s_oz, s_cost = _accumulate_day(by_date.get(ds), g_oz, g_cost, s_oz, s_cost)
        g_avg = (g_cost / g_oz) if g_oz > 0 else 0.0
        s_avg = (s_cost / s_oz) if s_oz > 0 else 0.0
        values.append(_pnl_row(ds, g_oz, g_avg, spot_gold.get(ds), s_oz, s_avg, spot_silver.get(ds)))
        cur = cur.fromordinal(cur.toordinal() + 1)
    return values


def _build_profit_series(all_recs: List[Dict[str, str]]) -> List[List[str]]:
    """Return values for a Profit sheet with columns:
    Date, Gold_Oz, Gold_AvgCost, Gold_Spot, Gold_PnL, Silver_Oz, Silver_AvgCost, Silver_Spot, Silver_PnL, Portfolio_PnL
    """
    by_date, min_date, max_date = _collect_profit_by_date(all_recs)
    if not min_date or not max_date:
        return []
    spot_gold = _spot_cad_series('gold', min_date, max_date)
    spot_silver = _spot_cad_series('silver', min_date, max_date)
    return _profit_walk_days(by_date, min_date, max_date, spot_gold, spot_silver)


def _read_existing_workbook_recs(wb: WorkbookContext) -> List[Dict[str, str]]:
    """Read all sheets from workbook and consolidate records that match our schema."""
    sheet_names = _list_worksheets(wb)
    existing_all: List[Dict[str, str]] = []
    for name in sheet_names:
        vals = _get_used_range_values(wb, name)
        if not vals:
            continue
        low = name.lower()
        if "silver" in low:
            assumed_metal = "silver"
        elif "gold" in low:
            assumed_metal = "gold"
        else:
            assumed_metal = None
        _hdrs, recs = _to_records(vals, assumed_metal=assumed_metal)
        if any(r.get("order_id") or r.get("total_oz") for r in recs):
            existing_all.extend(recs)
    return existing_all


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
    token = token or DEFAULT_OUTLOOK_TOKEN_CACHE
    if not client_id:
        raise SystemExit("No Outlook client_id configured in credentials.ini")

    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir=".cache")
    client.authenticate()

    wb = WorkbookContext(client, getattr(args, "drive_id"), getattr(args, "item_id"))

    existing_all = _read_existing_workbook_recs(wb)

    # Read local summaries and tag metal
    local_silver = _read_csv(getattr(args, "silver_csv"), metal="silver")
    local_gold = _read_csv(getattr(args, "gold_csv"), metal="gold")
    # Normalize to expected keys
    for r in local_silver + local_gold:
        r["metal"] = (r.get("metal") or "").lower()

    all_merged = _merge_all(existing_all, local_silver + local_gold)
    # Compose 'All' values
    all_values = _to_values_all(all_merged)

    # Build summary (computed values kept for future use if needed)
    _build_summary_values(all_merged)

    # Copy workbook to new item
    new_wb = _copy_item(wb, getattr(args, "out_name"))

    # Ensure sheets
    all_name = getattr(args, "all_sheet")
    sum_name = getattr(args, "summary_sheet")
    gold_name = "Gold"
    silver_name = "Silver"
    _ensure_sheet(new_wb, all_name)
    _ensure_sheet(new_wb, sum_name)
    _ensure_sheet(new_wb, gold_name)
    _ensure_sheet(new_wb, silver_name)

    # Write All and Summary (formulas)
    _write_range(new_wb, all_name, all_values)

    # Formula-driven Summary referencing All (D=metal, C=vendor, E=oz, F=cost_per_oz)
    sum_formulas = [
        ["Totals by Metal"],
        ["Metal", TOTAL_OZ_HDR, AVG_COST_HDR],
        _summary_row(all_name, "gold", "D"),
        _summary_row(all_name, "silver", "D"),
        [""],
        ["Totals by Vendor"],
        ["Vendor", TOTAL_OZ_HDR, AVG_COST_HDR],
        _summary_row(all_name, "TD", "C"),
        _summary_row(all_name, "Costco", "C"),
    ]
    _write_range(new_wb, sum_name, sum_formulas)

    # Gold/Silver sheets reference All via FILTER so data lives only once
    _write_filter_view(new_wb, all_name, gold_name, "gold")
    _write_filter_view(new_wb, all_name, silver_name, "silver")

    # Add charts on summary — chart totals by metal from Summary!B3:C4
    _add_chart(new_wb, sum_name, "ColumnClustered", "B3:C4", ChartPlacement(left=360, top=10))

    # Create Profit sheet with time-series PnL and charts
    profit_values = _build_profit_series(all_merged)
    if profit_values:
        profit_name = "Profit"
        _ensure_sheet(new_wb, profit_name)
        _write_range(new_wb, profit_name, profit_values)
        # Chart: Portfolio PnL over time (column J)
        rows = len(profit_values)
        # Data range J2:J{rows}
        _add_chart(new_wb, profit_name, "Line", f"J2:J{rows}", ChartPlacement(left=10, top=10, width=700, height=360))
        # Chart: Gold vs Silver spot and avg (columns C,D and G,H) — optional separate charts
        _add_chart(new_wb, profit_name, "Line", f"C2:D{rows}", ChartPlacement(left=10, top=380, width=700, height=280))
        _add_chart(new_wb, profit_name, "Line", f"G2:H{rows}", ChartPlacement(left=10, top=680, width=700, height=280))

    # Sheet order: Summary first, then Gold, then Silver; All last and hidden
    try:
        _set_sheet_position(new_wb, sum_name, 0)
        _set_sheet_position(new_wb, gold_name, 1)
        _set_sheet_position(new_wb, silver_name, 2)
    except Exception:  # nosec B110 - non-critical sheet positioning
        pass
    try:
        _set_sheet_visibility(new_wb, all_name, False)
    except Exception:  # nosec B110 - non-critical sheet visibility
        pass

    print("created consolidated workbook:", new_wb.drive_id, new_wb.item_id, "(Summary, Gold, Silver; All hidden)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
