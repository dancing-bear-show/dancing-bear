"""
Gmail precious-metals extractor.

Searches for TD Precious Metals and Costco order emails and extracts total
ounces of gold and silver from message bodies using simple heuristics.

Usage (defaults to profile=gmail_personal):
  python -m metals.gmail_extract [--profile gmail_personal] [--days 365]
"""
from __future__ import annotations

import argparse
import re
from typing import Tuple

from mail.config_resolver import resolve_paths_profile
from mail.gmail_api import GmailClient

from .constants import G_PER_OZ


# Compiled patterns for amount extraction
# [^\n]{0,60}? matches up to 60 non-newline chars (simplified from negative lookahead)
_PAT_FRAC_GE = re.compile(r"(?i)\b(\d+)\s*/\s*(\d+)\s*oz\b[^\n]{0,60}?\b(gold|silver)\b(?:[^\n]*?\bx\s*(\d+))?")
_PAT_OZ_GE = re.compile(r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*oz\b[^\n]{0,60}?\b(gold|silver)\b(?:[^\n]*?\bx\s*(\d+))?")
_PAT_G_GE = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b[^\n]{0,60}?\b(gold|silver)\b(?:[^\n]*?\bx\s*(\d+))?")  # nosec


def _ge_accumulate(
    gold_oz: float, silver_oz: float,
    metal: str, oz_unit: float, qty: float,
    key: Tuple[str, float, float], seen: set,
) -> Tuple[float, float]:
    if key in seen:
        return gold_oz, silver_oz
    seen.add(key)
    if metal.startswith('gold'):
        gold_oz += oz_unit * qty
    elif metal.startswith('silver'):
        silver_oz += oz_unit * qty
    return gold_oz, silver_oz


def _extract_frac_amounts(ln: str, gold_oz: float, silver_oz: float, seen: set) -> Tuple[float, float]:
    for m in _PAT_FRAC_GE.finditer(ln):
        num = float(m.group(1))
        den = float(m.group(2) or 1)
        metal = (m.group(3) or '').lower()
        qty = float(m.group(4) or 1)
        oz_unit = num / max(den, 1.0)
        gold_oz, silver_oz = _ge_accumulate(gold_oz, silver_oz, metal, oz_unit, qty, (metal, round(oz_unit, 6), qty), seen)
    return gold_oz, silver_oz


def _extract_oz_amounts(ln: str, gold_oz: float, silver_oz: float, seen: set) -> Tuple[float, float]:
    for m in _PAT_OZ_GE.finditer(ln):
        wt = float(m.group(1))
        metal = (m.group(2) or '').lower()
        qty = float(m.group(3) or 1)
        gold_oz, silver_oz = _ge_accumulate(gold_oz, silver_oz, metal, wt, qty, (metal, round(wt, 6), qty), seen)
    return gold_oz, silver_oz


def _extract_gram_amounts(ln: str, gold_oz: float, silver_oz: float, seen: set) -> Tuple[float, float]:
    for m in _PAT_G_GE.finditer(ln):
        wt_g = float(m.group(1))
        metal = (m.group(3) or '').lower()
        qty = float(m.group(4) or 1)
        oz_unit = wt_g / G_PER_OZ
        gold_oz, silver_oz = _ge_accumulate(gold_oz, silver_oz, metal, oz_unit, qty, (metal, round(oz_unit, 6), qty), seen)
    return gold_oz, silver_oz


def _extract_amounts(text: str) -> Tuple[float, float]:
    gold_oz = 0.0
    silver_oz = 0.0
    t = (text or "").replace("\u2013", "-").replace("\u2014", "-")
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    seen: set[Tuple[str, float, float]] = set()

    for ln in lines:
        gold_oz, silver_oz = _extract_frac_amounts(ln, gold_oz, silver_oz, seen)
        gold_oz, silver_oz = _extract_oz_amounts(ln, gold_oz, silver_oz, seen)
        gold_oz, silver_oz = _extract_gram_amounts(ln, gold_oz, silver_oz, seen)
    return gold_oz, silver_oz


_GE_ORDER_PAT = re.compile(r"(?i)order\s*#?\s*(\d{6,})")
_GE_QUERIES = [
    'from:noreply@td.com subject:"TD Precious Metals"',
    'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
    'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
    '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)',
]


def _ge_get_order_id(subject: str, text: str) -> str | None:
    m = _GE_ORDER_PAT.search(subject or '') or _GE_ORDER_PAT.search(text or '')
    return m.group(1) if m else None


def _ge_build_order_map(client: GmailClient, cand_ids: list) -> dict:
    """Build order_id -> (mid, recv_ms) map choosing latest message per order."""
    order_map: dict[str, tuple[str, int]] = {}
    for mid in cand_ids:
        msg = client.get_message(mid, fmt='full')
        hdrs = GmailClient.headers_to_dict(msg)
        sub = hdrs.get('subject', '')
        text = client.get_message_text(mid)
        oid = _ge_get_order_id(sub, text) or mid
        recv_ms = int(msg.get('internalDate') or 0)
        cur = order_map.get(oid)
        if not cur or recv_ms > cur[1]:
            order_map[oid] = (mid, recv_ms)
    return order_map


def run(profile: str = "gmail_personal", days: int | None = 365) -> int:  # noqa: ARG001 - days reserved for future use
    cred, tok = resolve_paths_profile(arg_credentials=None, arg_token=None, profile=profile)
    client = GmailClient(credentials_path=cred, token_path=tok, cache_dir=".cache")
    client.authenticate()

    cand_ids: list[str] = []
    for q in _GE_QUERIES:
        cand_ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
    cand_ids = list(dict.fromkeys(cand_ids))

    order_map = _ge_build_order_map(client, cand_ids)
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
