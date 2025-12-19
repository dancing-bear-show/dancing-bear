from __future__ import annotations

"""
Push gold/silver summary CSVs into an Excel workbook (OneDrive/SharePoint) via Microsoft Graph.

Requires an Outlook/Graph profile (client_id, tenant, token cache) to acquire tokens with MSAL.

Usage:
  python -m mail_assistant.utils.metals_excel \
    --profile outlook_personal \
    --drive-id <DRIVE_ID> --item-id <ITEM_ID> \
    --silver-csv out/metals/silver_summary.csv --silver-sheet Silver \
    --gold-csv out/metals/gold_summary.csv --gold-sheet Gold

This overwrites the respective sheets starting at A1 with CSV contents.
"""

import argparse
import csv
from typing import List, Optional

from personal_core.auth import resolve_outlook_credentials
from ..outlook_api import OutlookClient


def _col_letter(idx: int) -> str:
    # 1-based column index to Excel column letters
    s = ""
    n = idx
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_csv(path: str) -> List[List[str]]:
    rows: List[List[str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        for row in r:
            rows.append(list(row))
    return rows


def _write_sheet(client: OutlookClient, drive_id: str, item_id: str, sheet: str, values: List[List[str]]) -> None:
    import json
    import requests  # type: ignore

    base = f"{client.GRAPH}/drives/{drive_id}/items/{item_id}/workbook"
    # Clear a large range first to avoid stale content
    clear_url = f"{base}/worksheets('{sheet}')/range(address='A1:Z10000')/clear"
    requests.post(clear_url, headers=client._headers(), json={"applyTo": "contents"})

    if not values:
        return
    rows = len(values)
    cols = max(len(r) for r in values) if values else 0
    end_col = _col_letter(cols if cols > 0 else 1)
    addr = f"A1:{end_col}{rows}"
    url = f"{base}/worksheets('{sheet}')/range(address='{addr}')"
    body = {"values": values}
    res = requests.patch(url, headers=client._headers(), data=json.dumps(body))
    try:
        res.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Failed to write sheet {sheet}: {res.status_code} {res.text}") from e


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Push metal summary CSVs into an Excel workbook via Graph")
    p.add_argument("--profile", default="outlook_personal")
    p.add_argument("--drive-id", required=True)
    p.add_argument("--item-id", required=True)
    p.add_argument("--silver-csv")
    p.add_argument("--silver-sheet")
    p.add_argument("--gold-csv")
    p.add_argument("--gold-sheet")
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
        raise SystemExit("No Outlook client_id found in credentials.ini; configure [mail_assistant.<profile>]")

    client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir=".cache")
    client.authenticate()

    did = getattr(args, "drive_id")
    iid = getattr(args, "item_id")

    if getattr(args, "silver_csv", None) and getattr(args, "silver_sheet", None):
        vals = _read_csv(getattr(args, "silver_csv"))
        _write_sheet(client, did, iid, getattr(args, "silver_sheet"), vals)
    if getattr(args, "gold_csv", None) and getattr(args, "gold_sheet", None):
        vals = _read_csv(getattr(args, "gold_csv"))
        _write_sheet(client, did, iid, getattr(args, "gold_sheet"), vals)
    print("updated workbook", did, iid)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
