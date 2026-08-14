"""Price detection primitives for Gmail precious metals cost parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from .constants import MONEY_PATTERN
from .costs_common import find_money
from .vendors_parse_core import DEFAULT_PRICE_BAN
from .gmail_costs_qty_items import ExtractionContext, _build_uoz_patterns

_PAT_UNIT_PRICE = re.compile(r"(?i)\b(unit|each|ea|per)\b")


@dataclass
class PriceLineContext:
    """Context for evaluating whether a line contains a valid price."""
    has_metal: bool
    has_uoz_here: bool
    has_uoz_neighbor: bool
    mentions_price: bool
    mentions_total: bool
    kind: str


@dataclass
class CandidateLineContext:
    """Context for processing a candidate price line."""
    lines: List[str]
    j: int
    metal: str
    uoz_pat: re.Pattern[str] | None


def _try_anchored_extraction(
    ctx: ExtractionContext,
) -> Tuple[str, float, str] | None:
    """Try anchored extraction for compact table-in-one-line cases (TD/Costco)."""
    metal_kw = (ctx.metal or '').strip().lower()
    if not ctx.uoz_texts or metal_kw not in ('gold', 'silver'):
        return None
    uoz_alt = "|".join(ctx.uoz_texts)
    anch = re.search(fr"(?i)({uoz_alt}).{{0,200}}?\b{metal_kw}\b", ctx.ln) or \
           re.search(fr"(?i)\b{metal_kw}\b.{{0,200}}?({uoz_alt})", ctx.ln)
    if not anch:
        return None
    anchor_end = anch.end()
    m_money = MONEY_PATTERN.search(ctx.ln, pos=anchor_end)
    if not m_money or (m_money.start() - anchor_end) > 80:
        return None
    between = ctx.lower[anchor_end:m_money.start()]
    if re.search(r"(?i)\b(subtotal|shipping|tax|total)\b", between):
        return None
    cur = m_money.group(1).upper()
    amt = float(m_money.group(2).replace(',', ''))
    tail = ctx.lower[anchor_end:m_money.end()]
    kind = 'unit' if _PAT_UNIT_PRICE.search(tail) else 'unknown'
    before_amt = ctx.lower[max(0, m_money.start() - 80):m_money.start()]
    has_qty = bool(
        re.search(r"(?i)\bx\s*\d{1,3}\b", before_amt) or
        re.search(r"(?i)\bqty(?:uantity)?\s*:?\s*\d{1,3}\b", before_amt)
    )
    if has_qty and not _PAT_UNIT_PRICE.search(tail):
        kind = 'total' if ctx.vendor == 'td' else 'unit'
    return cur, amt, kind


def _determine_price_kind(
    lower: str, has_uoz_here: bool, has_uoz_neighbor: bool
) -> Tuple[str, bool, bool]:
    """Determine price kind from line content. Returns (kind, mentions_price, mentions_total)."""
    mentions_price = bool(re.search(r"(?i)\b(price|unit|each|ea|per)\b", lower))
    mentions_total = bool(re.search(r"(?i)\btotal\b", lower))
    if _PAT_UNIT_PRICE.search(lower):
        return "unit", mentions_price, mentions_total
    if re.search(r"(?i)\b(total\s*price|line\s*total|item\s*total)\b", lower):
        return "total", mentions_price, mentions_total
    if mentions_total and (mentions_price or has_uoz_here or has_uoz_neighbor):
        return "total", mentions_price, mentions_total
    return "unknown", mentions_price, mentions_total


def _check_uoz_in_neighbors(
    lines: List[str], j: int, uoz_pat: re.Pattern[str] | None
) -> bool:
    """Check if unit-oz pattern appears in neighboring lines.

    Args:
        lines: All text lines.
        j: Current line index.
        uoz_pat: Unit-oz regex pattern.

    Returns:
        True if pattern found in neighbors.
    """
    if not uoz_pat:
        return False
    return any(
        0 <= k < len(lines) and uoz_pat.search((lines[k] or "").lower())
        for k in (j - 1, j + 1)
    )


def _is_valid_price_line(ctx: PriceLineContext) -> bool:
    """Check if this line should be considered a valid price line."""
    # Skip if mentions "total" but kind isn't "total"
    if ctx.mentions_total and ctx.kind != "total":
        return False

    # Accept if line has metal, unit-oz, or price keywords
    return ctx.has_metal or ctx.has_uoz_here or ctx.has_uoz_neighbor or ctx.mentions_price


def _process_candidate_line(
    ln: str,
    lower: str,
    ctx: CandidateLineContext,
) -> Tuple[str, float, str] | None:
    """Process a single candidate line for price extraction.

    Returns:
        (currency, amount, kind) if valid price found, else None.
    """
    if DEFAULT_PRICE_BAN.search(ln):
        return None

    has_uoz_here = bool(ctx.uoz_pat and ctx.uoz_pat.search(lower))
    has_uoz_neighbor = _check_uoz_in_neighbors(ctx.lines, ctx.j, ctx.uoz_pat)

    money = find_money(ln)
    if not money:
        return None

    want = (ctx.metal or "").lower()
    has_metal = bool(want and want in lower)
    kind, mentions_price, mentions_total = _determine_price_kind(lower, has_uoz_here, has_uoz_neighbor)

    plc = PriceLineContext(
        has_metal=has_metal, has_uoz_here=has_uoz_here,
        has_uoz_neighbor=has_uoz_neighbor, mentions_price=mentions_price,
        mentions_total=mentions_total, kind=kind,
    )
    if _is_valid_price_line(plc):
        return money[0], money[1], kind

    return None


def _extract_amount_near_line(
    lines: List[str],
    idx: int,
    metal: str,
    unit_oz: float | None = None,
    vendor: str | None = None,
) -> Tuple[str, float, str] | None:
    """Return (currency, amount, kind) if a price appears near the line.

    Heuristics:
    - Search a wider window around the item line (idx +/- 12), prioritizing closer lines first.
    - Accept lines containing the metal keyword, or the exact unit-oz text, or price-related keywords.
    - Avoid global order totals: still ban 'subtotal', 'shipping', 'tax', 'order number'.
      Allow 'total' only when 'price' or a unit-oz mention is present (to pick up line 'Total Price').
    - kind in {unit,total,unknown}; caller uses kind to decide whether to multiply by quantity.
    """
    vendor_lower = (vendor or '').strip().lower()
    uoz_pat, uoz_texts = _build_uoz_patterns(unit_oz)

    candidates = [idx] + [x for d in range(1, 13) for x in (idx + d, idx - d)]
    for j in candidates:
        if not (0 <= j < len(lines)):
            continue

        ln = lines[j] or ""
        lower = ln.lower()

        # Try vendor-specific anchored extraction first
        if vendor_lower in ('td', 'costco'):
            extraction_ctx = ExtractionContext(
                ln=ln, lower=lower, metal=metal, unit_oz=unit_oz,
                uoz_texts=uoz_texts, vendor=vendor_lower,
            )
            result = _try_anchored_extraction(extraction_ctx)
            if result:
                return result

        # Try general price extraction
        cand_ctx = CandidateLineContext(lines=lines, j=j, metal=metal, uoz_pat=uoz_pat)
        result = _process_candidate_line(ln, lower, cand_ctx)
        if result:
            return result

    return None
