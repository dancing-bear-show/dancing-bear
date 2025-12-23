"""
Search Outlook Inbox for precious-metals order emails (TD, Costco, RCM) and report matches.

Uses Microsoft Graph $search with simple KQL-like queries. Prints counts per source
and lists recent matches with received time, from, and subject.

Usage:
  python -m mail.utils.outlook_metals_scan --profile outlook_personal --days 365 --top 50 --pages 3
"""
from __future__ import annotations

import argparse
from typing import Dict, List, Tuple

from core.auth import resolve_outlook_credentials
from mail.outlook_api import OutlookClient


QUERIES: List[Tuple[str, str]] = [
    ("TD", 'from:td.com OR from:tdsecurities.com OR "TD Precious Metals"'),
    ("Costco", 'from:costco.ca AND (order OR confirmation OR receipt OR shipped)'),
    ("RCM", 'from:mint.ca OR from:email.mint.ca OR from:royalcanadianmint.ca AND (order OR confirmation OR receipt OR shipped OR invoice)'),
]


def run(profile: str, days: int, top: int, pages: int, folder: str) -> int:
    client_id, tenant, token = resolve_outlook_credentials(profile, None, None, None)
    token = token or ".cache/.msal_token.json"
    if not client_id:
        raise SystemExit("No Outlook client_id configured; set it under [mail.<profile>] in credentials.ini")
    cli = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir=".cache")
    cli.authenticate()

    summary: Dict[str, List[str]] = {name: [] for (name, _q) in QUERIES}
    def _search_all(q: str) -> List[str]:
        import requests  # lazy import
        base = f"{cli.GRAPH}/me/messages"
        params = [f"$search=\"{q}\"", f"$top={int(top)}"]
        if days and int(days) > 0:
            import datetime as _dt
            start = _dt.datetime.utcnow() - _dt.timedelta(days=int(days))
            start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            params.append(f"$filter=receivedDateTime ge {start_iso}")
        url = base + "?" + "&".join(params)
        nxt = url
        ids: List[str] = []
        for _ in range(max(1, int(pages))):
            r = requests.get(nxt, headers=cli._headers_search())
            r.raise_for_status()
            data = r.json()
            vals = data.get("value", [])
            for m in vals:
                mid = m.get("id")
                if mid:
                    ids.append(mid)
            nxt = data.get("@odata.nextLink")
            if not nxt:
                break
        return ids

    for name, q in QUERIES:
        try:
            if (folder or 'inbox').lower() == 'all':
                ids = _search_all(q)
            else:
                ids = cli.search_inbox_messages(q, days=days, top=top, pages=pages, use_cache=False)
        except Exception:
            ids = []
        summary[name] = ids

    # Print summary counts
    print("Matches in Outlook Inbox (last", days, "days):")
    for name, ids in summary.items():
        print(f"- {name}: {len(ids)}")

    # List up to 10 most recent per source
    for name, ids in summary.items():
        if not ids:
            continue
        print(f"\n{name} recent:")
        for mid in ids[:10]:
            try:
                msg = cli.get_message(mid, select_body=False)
            except Exception:
                continue
            sub = (msg.get("subject") or "").strip()
            recv = (msg.get("receivedDateTime") or "")
            frm = (((msg.get("from") or {}).get("emailAddress") or {}).get("address") or "")
            print(f"- {recv[:19]} | {frm} | {sub[:100]}")
    return 0


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Search Outlook Inbox for metals order emails (TD, Costco, RCM)")
    p.add_argument("--profile", default="outlook_personal")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--folder", choices=["inbox", "all"], default="inbox", help="Search scope (Inbox only or all folders)")
    args = p.parse_args(argv)
    return run(
        profile=getattr(args, "profile", "outlook_personal"),
        days=int(getattr(args, "days", 365)),
        top=int(getattr(args, "top", 50)),
        pages=int(getattr(args, "pages", 3)),
        folder=str(getattr(args, "folder", "inbox")),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
