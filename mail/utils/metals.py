from __future__ import annotations

"""
Gmail precious-metals extractor.

Searches for TD Precious Metals and Costco order emails and extracts total
ounces of gold and silver from message bodies using simple heuristics.

Usage (defaults to profile=gmail_personal):
  python -m mail.utils.metals [--profile gmail_personal] [--days 365]
"""

import argparse
import re
from typing import Tuple

from ..config_resolver import resolve_paths_profile
from ..gmail_api import GmailClient


G_PER_OZ = 31.1035


def _extract_amounts(text: str) -> Tuple[float, float]:
    gold_oz = 0.0
    silver_oz = 0.0
    t = (text or "").replace("\u2013", "-").replace("\u2014", "-")
    lines = [l.strip() for l in t.splitlines() if l.strip()]

    # Track unique line items to avoid double counting repeated summaries
    seen_items: set[Tuple[str, float, float]] = set()  # (metal, oz_per_unit, qty)

    # Pattern A: fractional ounce with optional trailing quantity (e.g., "1/10 oz Gold ... x 2")
    pat_frac = re.compile(r"(?i)\b(\d+)\s*/\s*(\d+)\s*oz\b(?:(?!\n).){0,60}?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?")
    # Pattern B: decimal ounce with optional trailing quantity (e.g., "1 oz Silver ... x 5")
    # Ensure we don't misread the '10' in '1/10 oz' as '10 oz' by requiring no slash immediately before the number
    pat_oz = re.compile(r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*oz\b(?:(?!\n).){0,60}?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?")
    # Pattern C: grams with optional trailing quantity
    pat_g = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b(?:(?!\n).){0,60}?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?")

    for ln in lines:
        for m in pat_frac.finditer(ln):
            num = float(m.group(1)); den = float(m.group(2) or 1)
            metal = (m.group(3) or '').lower()
            qty = float(m.group(4) or 1)
            oz_unit = num / max(den, 1.0)
            key = (metal, round(oz_unit, 6), qty)
            if key in seen_items:
                continue
            seen_items.add(key)
            if metal.startswith('gold'):
                gold_oz += oz_unit * qty
            elif metal.startswith('silver'):
                silver_oz += oz_unit * qty
        for m in pat_oz.finditer(ln):
            wt = float(m.group(1))
            metal = (m.group(2) or '').lower()
            qty = float(m.group(3) or 1)
            key = (metal, round(wt, 6), qty)
            if key in seen_items:
                continue
            seen_items.add(key)
            if metal.startswith('gold'):
                gold_oz += wt * qty
            elif metal.startswith('silver'):
                silver_oz += wt * qty
        for m in pat_g.finditer(ln):
            wt_g = float(m.group(1))
            metal = (m.group(3) or '').lower()
            qty = float(m.group(4) or 1)
            oz_unit = wt_g / G_PER_OZ
            key = (metal, round(oz_unit, 6), qty)
            if key in seen_items:
                continue
            seen_items.add(key)
            if metal.startswith('gold'):
                gold_oz += oz_unit * qty
            elif metal.startswith('silver'):
                silver_oz += oz_unit * qty
    return gold_oz, silver_oz


def run(profile: str = "gmail_personal", days: int | None = 365) -> int:
    cred, tok = resolve_paths_profile(arg_credentials=None, arg_token=None, profile=profile)
    client = GmailClient(credentials_path=cred, token_path=tok, cache_dir=".cache")
    client.authenticate()

    queries = [
        'from:noreply@td.com subject:"TD Precious Metals"',
        'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
        'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
        # Royal Canadian Mint (RCM) confirmations / receipts / shipping
        '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)'
    ]

    # Gather candidates per order id to avoid double-counting (TD/Costco patterns)
    def get_order_id(subject: str, text: str) -> str | None:
        s = subject or ''
        t = text or ''
        m = re.search(r"(?i)order\s*#?\s*(\d{6,})", s) or re.search(r"(?i)order\s*#?\s*(\d{6,})", t)
        return m.group(1) if m else None

    # Fetch ids and build map: order_id -> list[(mid, recv_ms, subject)]
    cand_ids: list[str] = []
    for q in queries:
        cand_ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
    cand_ids = list(dict.fromkeys(cand_ids))

    order_map: dict[str, tuple[str, int]] = {}  # order_id -> (mid, internalDate_ms)
    meta_needed: list[str] = []
    for mid in cand_ids:
        meta_needed.append(mid)

    # Resolve metadata and choose the latest message per order
    for mid in meta_needed:
        msg = client.get_message(mid, fmt='full')
        hdrs = GmailClient.headers_to_dict(msg)
        sub = hdrs.get('subject','')
        text = client.get_message_text(mid)
        oid = get_order_id(sub, text) or mid  # fallback to msg id
        recv_ms = int(msg.get('internalDate') or 0)
        cur = order_map.get(oid)
        if not cur or recv_ms > cur[1]:
            order_map[oid] = (mid, recv_ms)

    uniq_ids = [mid for (mid, _) in order_map.values()]

    total_gold = 0.0
    total_silver = 0.0
    samples: list[tuple[str, float, float]] = []
    for mid in uniq_ids:
        text = client.get_message_text(mid)
        g, s = _extract_amounts(text)
        total_gold += g
        total_silver += s
        if g or s:
            samples.append((mid, round(g, 3), round(s, 3)))

    print(f"gold_oz={total_gold:.3f} silver_oz={total_silver:.3f}")
    if samples:
        print("samples:")
        for mid, g, s in samples[:10]:
            print(f"- {mid}: gold={g} silver={s}")
    else:
        print("no line-items detected; ensure messages include item weights")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Extract gold/silver totals from Gmail order emails")
    p.add_argument("--profile", default="gmail_personal")
    p.add_argument("--days", type=int, default=365)
    args = p.parse_args(argv)
    return run(profile=getattr(args, "profile", "gmail_personal"), days=getattr(args, "days", 365))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
