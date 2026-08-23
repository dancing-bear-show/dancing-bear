"""
Create a single consolidated 'All' data sheet (gold + silver) and a 'Summary' sheet with
aggregations and charts, based on an existing OneDrive Excel workbook. The tool reads the
existing workbook, merges with local summaries, and writes to a new file.

Usage:
  python -m metals.excel_all \
    --profile outlook_personal \
    --drive-id <DRIVE_ID> --item-id <ITEM_ID> \
    --silver-csv silver_summary.csv \
    --gold-csv gold_summary.csv \
    --all-sheet All --summary-sheet Summary \
    --out-name "Metals Summary (Merged).xlsx"
"""
from __future__ import annotations

import argparse
import json
from typing import List, Optional

from core.auth import resolve_outlook_credentials
from core.constants import DEFAULT_OUTLOOK_TOKEN_CACHE, DEFAULT_REQUEST_TIMEOUT
from core.outlook import OutlookClient
from .workbook import WorkbookContext, ChartPlacement, col_letter as _col_letter, write_range_to_sheet as _write_range, pad_rows as _pad_rows  # noqa: F401

from .excel_io import (  # noqa: F401
    _read_csv,
    _list_worksheets,
    _get_used_range_values,
    _to_records,
    _norm_row,
    _merge_all_key,
    _CORE_FIELDS,
    _merge_all_update,
    _merge_all,
    _poll_async_operation,
    _ensure_sheet,
    _set_sheet_position,
    _set_sheet_visibility,
    _to_values_all,
    _read_existing_workbook_recs,
)
from .excel_chart import (  # noqa: F401
    AVG_COST_HDR,
    TOTAL_OZ_HDR,
    _SUMMARY_TITLES,
    _add_chart,
    _write_filter_view,
    _sumif_formula,
    _avgcost_formula,
    _summary_row,
    _agg_rec_update,
    _aggregate_summary_recs,
    _build_metal_rows,
    _build_vendor_rows,
    _build_monthly_avg_rows,
    _build_monthly_oz_rows,
    _build_summary_blocks,
    _stitch_summary_blocks,
    _build_summary_values,
    _fill_date_gaps,
    _fetch_yahoo_series,
    _usd_to_cad_series,
    _spot_cad_series,
    MetalPosition,
    _pnl_row,
    _accumulate_day,
    _profit_walk_days,
    _parse_profit_rec,
    _collect_profit_by_date,
    _build_profit_series,
)


def _copy_item(wb: WorkbookContext, new_name: str) -> WorkbookContext:
    import requests  # type: ignore

    meta = requests.get(
        f"{wb.client.GRAPH}/drives/{wb.drive_id}/items/{wb.item_id}",
        headers=wb.headers(),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    ).json()
    parent_id = ((meta or {}).get("parentReference") or {}).get("id")
    body = {"name": new_name}
    if parent_id:
        body["parentReference"] = {"id": parent_id}

    copy_url = f"{wb.client.GRAPH}/drives/{wb.drive_id}/items/{wb.item_id}/copy"
    resp = requests.post(
        copy_url, headers=wb.headers(), data=json.dumps(body), timeout=DEFAULT_REQUEST_TIMEOUT
    )
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


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Create single 'All' sheet + 'Summary' with charts from workbook + local summaries"
    )
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
        _add_chart(
            new_wb, profit_name, "Line", f"J2:J{rows}",
            ChartPlacement(left=10, top=10, width=700, height=360),
        )
        # Chart: Gold vs Silver spot and avg (columns C,D and G,H) — optional separate charts
        _add_chart(
            new_wb, profit_name, "Line", f"C2:D{rows}",
            ChartPlacement(left=10, top=380, width=700, height=280),
        )
        _add_chart(
            new_wb, profit_name, "Line", f"G2:H{rows}",
            ChartPlacement(left=10, top=680, width=700, height=280),
        )

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
