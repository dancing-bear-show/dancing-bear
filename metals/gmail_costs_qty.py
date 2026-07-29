"""Quantity and price extraction primitives for Gmail precious metals cost parsing."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from core.text_utils import normalize_unicode

from .constants import (
    G_PER_OZ,
    MONEY_PATTERN,
    PAT_FRAC_OZ as _PAT_FRAC,
    PAT_DECIMAL_OZ as _PAT_OZ,
    PAT_GRAMS as _PAT_G,
    QTY_PATTERNS as _PAT_QTY_LIST,
    BUNDLE_PATTERNS as _PAT_BUNDLE_LIST,
    PAT_SKU as _PAT_ITEM_SKU,
    PAT_LEADING_QTY as _PAT_LEADING_QTY,
    SKU_BUNDLE_MAP as _SKU_BUNDLE_MAP,
    SKU_UNIT_MAP_SILVER as _SKU_UNIT_MAP_SILVER,
    SKU_UNIT_MAP_GOLD as _SKU_UNIT_MAP_GOLD,
    PHRASE_MAP_SILVER as _PHRASE_MAP_SILVER,
)
from .costs_common import find_money
from .vendors import DEFAULT_PRICE_BAN

_PAT_UNIT_PRICE = re.compile(r"(?i)\b(unit|each|ea|per)\b")


@dataclass
class LineItemContext:
    """Context for applying quantity heuristics to a line item."""
    lines: List[str]
    ln: str
    match: re.Match[str]
    idx: int
    unit_oz: float
    metal: str
    qty: float
    explicit_qty: bool


@dataclass
class ExtractionContext:
    """Context for anchored price extraction."""
    ln: str
    lower: str
    metal: str
    unit_oz: float | None
    uoz_texts: List[str]
    vendor: str


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


def _extract_first_match_group(
    pattern: re.Pattern[str], text: str, min_val: int, max_val: int
) -> float | None:
    """Extract first matching numeric group within [min_val, max_val] range."""
    m = pattern.search(text or "")
    if not m:
        return None
    for g in (1, 2):
        try:
            val = m.group(g)
        except Exception:  # nosec B110 - group may not exist
            val = None
        if val and val.isdigit():
            n = int(val)
            if min_val <= n <= max_val:
                return float(n)
    return None


def _explicit_qty_near(lines: List[str], idx: int) -> float | None:
    """Look near the line for explicit quantity indicators (e.g., 'x 25', 'Qty 2')."""
    for j in (idx, idx + 1, idx - 1, idx + 2):
        if 0 <= j < len(lines):
            for pat in _PAT_QTY_LIST:
                result = _extract_first_match_group(pat, lines[j], 1, 200)
                if result:
                    return result
    return None


def _bundle_qty_near(lines: List[str], idx: int) -> float | None:
    """Look for bundle indicators (e.g., 'roll of 25', 'tube of 25', '25-pack')."""
    for j in (idx, idx + 1, idx - 1, idx + 2):
        if 0 <= j < len(lines):
            s = lines[j]
            for pat in _PAT_BUNDLE_LIST:
                result = _extract_first_match_group(pat, s, 2, 200)
                if result:
                    return result
            m_item = _PAT_ITEM_SKU.search(s or '')
            if m_item and m_item.group(1) in _SKU_BUNDLE_MAP:
                return _SKU_BUNDLE_MAP[m_item.group(1)]
    return None


def _get_metal_maps(metal_ctx: str) -> Tuple[Dict, Dict]:
    """Get SKU and phrase maps for the given metal context.

    Returns:
        (sku_unit_map, phrase_map) for the metal.
    """
    metal_key = (metal_ctx or '').strip().lower()
    sku_unit_map = _SKU_UNIT_MAP_SILVER if metal_key == 'silver' else _SKU_UNIT_MAP_GOLD
    phrase_map = _PHRASE_MAP_SILVER if metal_key == 'silver' else {}
    return sku_unit_map, phrase_map


def _check_sku_match(line: str, sku_unit_map: Dict) -> float | None:
    """Check if line contains a SKU that maps to a unit-oz value."""
    m_item = _PAT_ITEM_SKU.search(line or '')
    if m_item and m_item.group(1) in sku_unit_map:
        return sku_unit_map[m_item.group(1)]
    return None


def _check_phrase_match(line: str, phrase_map: Dict) -> float | None:
    """Check if line contains a phrase that maps to a unit-oz value."""
    s_low = (line or '').lower()
    for ph, uoz in phrase_map.items():
        if ph in s_low:
            return uoz
    return None


def _unit_oz_override_near(
    lines: List[str], idx: int, metal_ctx: str
) -> float | None:
    """Map item numbers/phrases to unit-oz when emails omit explicit size."""
    sku_unit_map, phrase_map = _get_metal_maps(metal_ctx)

    for j in (idx, idx + 1, idx - 1, idx + 2):
        if not (0 <= j < len(lines)):
            continue

        # Check SKU match first
        sku_result = _check_sku_match(lines[j], sku_unit_map)
        if sku_result:
            return sku_result

        # Check phrase match
        phrase_result = _check_phrase_match(lines[j], phrase_map)
        if phrase_result:
            return phrase_result

    return None


def _extract_leading_qty(ln: str, match_obj: re.Match[str]) -> float | None:
    """Extract quantity from text before the match."""
    pre = ln[max(0, match_obj.start() - 120):match_obj.start()]
    mpre = _PAT_LEADING_QTY.search(pre)
    return float(mpre.group(1)) if mpre else None


def _determine_quantity(
    lines: List[str], idx: int, unit_oz: float, pre_q: float | None
) -> float:
    """Determine the final quantity using various heuristics.

    Args:
        lines: All text lines.
        idx: Current line index.
        unit_oz: Unit ounces value.
        pre_q: Quantity extracted from leading text.

    Returns:
        Determined quantity.
    """
    eq = _explicit_qty_near(lines, idx)
    if eq:
        # If we have both pre_q and eq, prefer pre_q for ~1oz items when eq < pre_q
        if pre_q and (0.98 <= unit_oz <= 1.02) and eq < pre_q:
            return pre_q
        return eq

    if pre_q:
        return pre_q

    # Try bundle quantity as last resort for ~1oz items
    bq = _bundle_qty_near(lines, idx)
    if bq and (0.98 <= unit_oz <= 1.02):
        return bq

    return 1.0


def _apply_qty_heuristics(ctx: LineItemContext) -> Tuple[float, float]:
    """Apply quantity and unit-oz heuristics. Returns (qty, unit_oz)."""
    qty, unit_oz = ctx.qty, ctx.unit_oz

    # Apply quantity heuristics only if qty is ~1 and not explicitly stated
    if math.isclose(qty, 1.0) and not ctx.explicit_qty:
        pre_q = _extract_leading_qty(ctx.ln, ctx.match)
        qty = _determine_quantity(ctx.lines, ctx.idx, unit_oz, pre_q)

    # Apply unit-oz override if available
    uov = _unit_oz_override_near(ctx.lines, ctx.idx, ctx.metal)
    if uov:
        unit_oz = uov

    return qty, unit_oz


def _parse_frac_match(m: re.Match[str]) -> Tuple[float, str, float, bool]:
    """Parse fractional oz match. Returns (unit_oz, metal, qty, explicit_qty)."""
    num, den = float(m.group(1)), float(m.group(2) or 1)
    return num / max(den, 1.0), (m.group(3) or '').lower(), float(m.group(4) or 1), m.group(4) is not None


def _parse_oz_match(m: re.Match[str]) -> Tuple[float, str, float, bool]:
    """Parse decimal oz match. Returns (unit_oz, metal, qty, explicit_qty)."""
    return float(m.group(1)), (m.group(2) or '').lower(), float(m.group(3) or 1), m.group(3) is not None


def _parse_gram_match(m: re.Match[str]) -> Tuple[float, str, float, bool]:
    """Parse gram match. Returns (unit_oz, metal, qty, explicit_qty)."""
    wt_g = float(m.group(1))
    return wt_g / G_PER_OZ, (m.group(3) or '').lower(), float(m.group(4) or 1), m.group(4) is not None


def _extract_line_items(
    text: str,
) -> Tuple[List[Dict], List[str]] | None:
    """Return (items, lines) where items are dicts {metal, unit_oz, qty, idx}.

    Handles fractional ounces (e.g., '1/10 oz Gold ... x 2'), decimal ounces ('1 oz Silver x 4'),
    and grams, each with optional trailing 'x N' quantity.
    Returns None for empty text.
    """
    t = normalize_unicode(text or '')
    lines: List[str] = [line.strip() for line in t.splitlines() if line.strip()]
    if not lines:
        return None

    items: List[Dict] = []
    patterns = [(_PAT_FRAC, _parse_frac_match), (_PAT_OZ, _parse_oz_match), (_PAT_G, _parse_gram_match)]
    for idx, ln in enumerate(lines):
        for pat, parser in patterns:
            for m in pat.finditer(ln):
                unit_oz, metal, qty, explicit_qty = parser(m)
                ctx = LineItemContext(
                    lines=lines, ln=ln, match=m, idx=idx,
                    unit_oz=unit_oz, metal=metal, qty=qty, explicit_qty=explicit_qty,
                )
                qty, unit_oz = _apply_qty_heuristics(ctx)
                items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})
    return items, lines


def _build_uoz_patterns(
    unit_oz: float | None,
) -> Tuple[re.Pattern[str] | None, List[str]]:
    """Build unit-oz regex pattern and textual representations. Returns (uoz_pat, uoz_texts)."""
    if not unit_oz or unit_oz <= 0:
        return None, []
    u = int(unit_oz) if abs(unit_oz - int(unit_oz)) < 1e-6 else unit_oz
    uoz_pat = re.compile(rf"(?i)\b{u}\s*oz\b")
    uoz_texts = [fr"\b{u}\s*oz\b"]
    if unit_oz < 1.0:
        inv = 1.0 / unit_oz
        inv_i = int(round(inv))
        if inv_i >= 2 and abs(inv - inv_i) < 1e-3 and inv_i <= 100:
            uoz_texts.append(fr"\b1\s*/\s*{inv_i}\s*oz\b")
    return uoz_pat, uoz_texts


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
