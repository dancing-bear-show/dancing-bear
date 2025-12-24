from __future__ import annotations

import argparse
import json
from typing import Dict, List, Optional

from core.auth import resolve_outlook_credentials
from mail.outlook_api import OutlookClient


def _headers(client: OutlookClient) -> Dict[str, str]:
    return client._headers()  # noqa: SLF001 (intentional internal use)


def _list_sheets(client: OutlookClient, drive_id: str, item_id: str) -> List[Dict[str, str]]:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets?$select=id,name,position,visibility"
    r = requests.get(url, headers=_headers(client))  # nosec B113
    r.raise_for_status()
    return (r.json() or {}).get("value", [])


def _delete_sheet(client: OutlookClient, drive_id: str, item_id: str, name: str) -> None:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{name}')"
    requests.delete(url, headers=_headers(client))  # nosec B113


def _list_charts(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> List[Dict[str, str]]:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/charts?$select=id,name"
    r = requests.get(url, headers=_headers(client))  # nosec B113
    if r.status_code >= 400:
        return []
    return (r.json() or {}).get("value", [])


def _set_chart_title(client: OutlookClient, drive_id: str, item_id: str, sheet: str, chart_id: str, title: str) -> None:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/charts('{chart_id}')/title"
    requests.patch(url, headers=_headers(client), data=json.dumps({"text": title, "visible": True}))  # nosec B113


def _set_axis_titles(client: OutlookClient, drive_id: str, item_id: str, sheet: str, chart_id: str, category: Optional[str], value: Optional[str]) -> None:
    import requests  # type: ignore
    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/charts('{chart_id}')/axes"
    if category:
        requests.patch(f"{base}/categoryAxis/title", headers=_headers(client), data=json.dumps({"text": category, "visible": True}))  # nosec B113
    if value:
        requests.patch(f"{base}/valueAxis/title", headers=_headers(client), data=json.dumps({"text": value, "visible": True}))  # nosec B113


def _used_rows(client: OutlookClient, drive_id: str, item_id: str, sheet: str) -> int:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/usedRange(valuesOnly=true)?$select=values"
    r = requests.get(url, headers=_headers(client))  # nosec B113
    if r.status_code >= 400:
        return 0
    vals = (r.json() or {}).get('values') or []
    return len(vals)


def _set_chart_data(client: OutlookClient, drive_id: str, item_id: str, sheet: str, chart_id: str, addr: str) -> None:
    import requests  # type: ignore
    url = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets('{sheet}')/charts('{chart_id}')/setData"
    requests.post(url, headers=_headers(client), data=json.dumps({"sourceData": f"'{sheet}'!{addr}", "seriesBy": "Auto"}))  # nosec B113


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
    token = token or '.cache/.msal_token.json'
    if not client_id:
        raise SystemExit('No Outlook client_id configured')
    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir='.cache')
    client.authenticate()

    drive = getattr(args, 'drive_id')
    item = getattr(args, 'item_id')
    # Remove untitled/default sheets (anything not in allowed set and with default-like names)
    allowed = {getattr(args, 'summary_sheet'), getattr(args, 'gold_sheet'), getattr(args, 'silver_sheet'), getattr(args, 'all_sheet'), getattr(args, 'profit_sheet')}
    sheets = _list_sheets(client, drive, item)
    for s in sheets:
        name = s.get('name') or ''
        low = name.lower()
        if name not in allowed and (low.startswith('sheet') or name.strip() == ''):
            _delete_sheet(client, drive, item, name)

    # Tidy Summary chart titles
    sum_name = getattr(args, 'summary_sheet')
    charts = _list_charts(client, drive, item, sum_name)
    if charts:
        # First chart is Totals by Metal
        _set_chart_title(client, drive, item, sum_name, charts[0]['id'], 'Totals by Metal')
        _set_axis_titles(client, drive, item, sum_name, charts[0]['id'], category=None, value=None)

    # Tidy Profit charts (Portfolio PnL; Gold spot vs avg; Silver spot vs avg)
    profit = getattr(args, 'profit_sheet')
    charts = _list_charts(client, drive, item, profit)
    if charts:
        rows = max(_used_rows(client, drive, item, profit), 2)
        try:
            ch = charts[0]
            _set_chart_title(client, drive, item, profit, ch['id'], 'Portfolio PnL (CAD)')
            _set_axis_titles(client, drive, item, profit, ch['id'], category='Date', value='C$')
            _set_chart_data(client, drive, item, profit, ch['id'], f"J2:J{rows}")
        except Exception:
            pass  # nosec B110 - non-critical chart update
        if len(charts) > 1:
            try:
                ch = charts[1]
                _set_chart_title(client, drive, item, profit, ch['id'], 'Gold: Spot vs Avg (C$/oz)')
                _set_axis_titles(client, drive, item, profit, ch['id'], category='Date', value='C$/oz')
                _set_chart_data(client, drive, item, profit, ch['id'], f"C2:D{rows}")
            except Exception:
                pass  # nosec B110 - non-critical chart update
        if len(charts) > 2:
            try:
                ch = charts[2]
                _set_chart_title(client, drive, item, profit, ch['id'], 'Silver: Spot vs Avg (C$/oz)')
                _set_axis_titles(client, drive, item, profit, ch['id'], category='Date', value='C$/oz')
                _set_chart_data(client, drive, item, profit, ch['id'], f"G2:H{rows}")
            except Exception:
                pass  # nosec B110 - non-critical chart update

    print('tidied workbook charts and sheets')
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
