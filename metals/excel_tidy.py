from __future__ import annotations

import argparse
import json
from typing import Dict, List, Optional

from core.auth import resolve_outlook_credentials
from core.constants import DEFAULT_OUTLOOK_TOKEN_CACHE, DEFAULT_REQUEST_TIMEOUT
from core.http import HttpClient
from mail.outlook_api import OutlookClient
from .workbook import WorkbookContext


def _list_sheets(wb: WorkbookContext) -> List[Dict[str, str]]:
    url = f"{wb.base_url}/worksheets?$select=id,name,position,visibility"
    r = HttpClient(url, default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).get("")
    return (r.json() or {}).get("value", [])


def _delete_sheet(wb: WorkbookContext, name: str) -> None:
    try:
        HttpClient(wb.sheet_url(name), default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).delete("")
    except Exception:  # nosec B110 - delete is best-effort
        pass


def _list_charts(wb: WorkbookContext, sheet: str) -> List[Dict[str, str]]:
    url = f"{wb.sheet_url(sheet)}/charts?$select=id,name"
    try:
        r = HttpClient(url, default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).get("")
    except Exception:  # nosec B110 - return empty on error
        return []
    return (r.json() or {}).get("value", [])


def _set_chart_title(wb: WorkbookContext, sheet: str, chart_id: str, title: str) -> None:
    url = f"{wb.chart_url(sheet, chart_id)}/title"
    try:
        HttpClient(url, default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).patch(
            "", data=json.dumps({"text": title, "visible": True})
        )
    except Exception:  # nosec B110 - chart title update is best-effort
        pass


def _set_axis_titles(wb: WorkbookContext, sheet: str, chart_id: str, category: Optional[str], value: Optional[str]) -> None:
    base = f"{wb.chart_url(sheet, chart_id)}/axes"
    _hclient = HttpClient("", default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT)
    if category:
        try:
            _hclient.patch(f"{base}/categoryAxis/title", data=json.dumps({"text": category, "visible": True}))
        except Exception:  # nosec B110 - axis title update is best-effort
            pass
    if value:
        try:
            _hclient.patch(f"{base}/valueAxis/title", data=json.dumps({"text": value, "visible": True}))
        except Exception:  # nosec B110 - axis title update is best-effort
            pass


def _used_rows(wb: WorkbookContext, sheet: str) -> int:
    url = f"{wb.sheet_url(sheet)}/usedRange(valuesOnly=true)?$select=values"
    try:
        r = HttpClient(url, default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).get("")
    except Exception:  # nosec B110 - return 0 on error
        return 0
    vals = (r.json() or {}).get('values') or []
    return len(vals)


def _set_chart_data(wb: WorkbookContext, sheet: str, chart_id: str, addr: str) -> None:
    url = f"{wb.chart_url(sheet, chart_id)}/setData"
    try:
        HttpClient(url, default_headers=wb.headers(), timeout=DEFAULT_REQUEST_TIMEOUT).post(
            "", data=json.dumps({"sourceData": f"'{sheet}'!{addr}", "seriesBy": "Auto"})
        )
    except Exception:  # nosec B110 - chart data update is best-effort
        pass


def _tidy_default_sheets(wb: WorkbookContext, allowed: set) -> None:
    """Remove default/untitled sheets not in the allowed set."""
    for s in _list_sheets(wb):
        name = s.get('name') or ''
        low = name.lower()
        if name not in allowed and (low.startswith('sheet') or name.strip() == ''):
            _delete_sheet(wb, name)


def _tidy_profit_charts(wb: WorkbookContext, profit: str) -> None:
    """Set titles and data ranges for the profit sheet charts."""
    charts = _list_charts(wb, profit)
    if not charts:
        return
    rows = max(_used_rows(wb, profit), 2)
    _configs = [
        (0, 'Portfolio PnL (CAD)', 'Date', 'C$', f"J2:J{rows}"),
        (1, 'Gold: Spot vs Avg (C$/oz)', 'Date', 'C$/oz', f"C2:D{rows}"),
        (2, 'Silver: Spot vs Avg (C$/oz)', 'Date', 'C$/oz', f"G2:H{rows}"),
    ]
    for idx, title, cat, val, data_range in _configs:
        if idx >= len(charts):
            break
        try:
            ch = charts[idx]
            _set_chart_title(wb, profit, ch['id'], title)
            _set_axis_titles(wb, profit, ch['id'], category=cat, value=val)
            _set_chart_data(wb, profit, ch['id'], data_range)
        except Exception:  # nosec B110 - non-critical chart update
            pass


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Tidy metals workbook: set chart titles, fix ranges, remove unnamed sheets")
    p.add_argument("--profile", default="outlook_personal")
    p.add_argument("--drive-id", required=True)
    p.add_argument("--item-id", required=True)
    p.add_argument("--summary-sheet", default="Summary")
    p.add_argument("--all-sheet", default="All")
    p.add_argument("--gold-sheet", default="Gold")
    p.add_argument("--silver-sheet", default="Silver")
    p.add_argument("--profit-sheet", default="Profit")
    args = p.parse_args(argv)

    client_id, tenant, token = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token = token or DEFAULT_OUTLOOK_TOKEN_CACHE
    if not client_id:
        raise SystemExit('No Outlook client_id configured')
    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir='.cache')
    client.authenticate()

    wb = WorkbookContext(client, getattr(args, 'drive_id'), getattr(args, 'item_id'))

    allowed = {
        getattr(args, 'summary_sheet'), getattr(args, 'gold_sheet'),
        getattr(args, 'silver_sheet'), getattr(args, 'all_sheet'),
        getattr(args, 'profit_sheet'),
    }
    _tidy_default_sheets(wb, allowed)

    sum_name = getattr(args, 'summary_sheet')
    charts = _list_charts(wb, sum_name)
    if charts:
        _set_chart_title(wb, sum_name, charts[0]['id'], 'Totals by Metal')
        _set_axis_titles(wb, sum_name, charts[0]['id'], category=None, value=None)

    _tidy_profit_charts(wb, getattr(args, 'profit_sheet'))

    print('tidied workbook charts and sheets')
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
