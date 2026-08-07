"""Core parsing primitives for vendor email parsing."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.text_utils import normalize_unicode

from .constants import (
    G_PER_OZ,
    MONEY_PATTERN,
    PAT_FRAC_OZ,
    PAT_DECIMAL_OZ,
    PAT_GRAMS,
    QTY_PATTERNS,
    BUNDLE_PATTERNS,
    PAT_SKU,
    PRICE_BAN_DEFAULT,
    SKU_BUNDLE_MAP,
)
from .costs_common import get_price_band

# Compiled patterns for price classification
_PAT_UNIT = re.compile(r"(?i)\b(unit|each|ea|per)\b")
_PAT_TOTAL = re.compile(r"(?i)\btotal\b")

# Alias for backwards compatibility
DEFAULT_PRICE_BAN = PRICE_BAN_DEFAULT

# Pattern configs: (pattern, type_key)
_WEIGHT_PATTERNS = [
    (PAT_FRAC_OZ, 'frac'),
    (PAT_DECIMAL_OZ, 'decimal'),
    (PAT_GRAMS, 'grams'),
]


@dataclass
class LineItem:
    """A parsed line item from an order email."""
    metal: str
    unit_oz: float
    qty: float
    idx: int  # line index in source text


@dataclass
class PriceHit:
    """A price found near a line item."""
    amount: float
    kind: str  # 'unit', 'total', or 'unknown'


@dataclass
class PriceSearchContext:
    """Context for searching for prices near a line item."""
    lines: List[str]  # All email lines
    idx: int  # Index of line item in lines
    metal: str  # Metal type (gold, silver)
    unit_oz: float  # Unit weight in ounces
    window: int = 13  # Search window size
    ban_pattern: Optional[re.Pattern] = None  # Pattern to exclude lines
    forward_only: bool = False  # Search only forward from idx


@dataclass
class BundleSearchContext:
    """Context for searching for bundle quantities."""
    lines: List[str]  # All email lines
    idx: int  # Index of line item in lines
    sku_map: Optional[Dict[str, float]] = None  # SKU to quantity mapping
    window: int = 4  # Search window size


def iter_nearby_lines(
    lines: List[str], idx: int, window: int, forward_only: bool = False
) -> List[Tuple[int, str]]:
    """Return (line_index, line_text) pairs near idx within window."""
    result: List[Tuple[int, str]] = []
    seen: set[int] = set()
    for d in range(window):
        candidates = [idx + d] if forward_only else [idx + d, idx - d]
        for j in candidates:
            if j in seen or not (0 <= j < len(lines)):
                continue
            seen.add(j)
            result.append((j, lines[j] or ""))
    return result


def _qty_from_line(ln: str) -> Optional[float]:
    """Extract quantity from a single line using QTY_PATTERNS. Returns None if not found."""
    for pat in QTY_PATTERNS:
        m = pat.search(ln)
        if not m:
            continue
        raw = m.group(1)
        if not (raw and raw.isdigit()):
            continue
        n = int(raw)
        if 1 <= n <= 200:
            return float(n)
    return None


def find_qty_near(lines: List[str], idx: int, window: int = 4) -> Optional[float]:
    """Find explicit quantity near a line index."""
    for _, ln in iter_nearby_lines(lines, idx, window):
        qty = _qty_from_line(ln)
        if qty is not None:
            return qty
    return None


def infer_metal_from_context(text: str) -> str:
    """Infer metal type from surrounding text."""
    t = (text or '').lower()
    if 'gold' in t:
        return 'gold'
    if 'silver' in t:
        return 'silver'
    return ''


def _parse_frac_match(m: re.Match) -> Tuple[float, str, float]:
    """Parse fractional oz pattern: 1/2 oz gold (2)."""
    num, den = float(m.group(1)), float(m.group(2) or 1)
    unit_oz = num / max(den, 1.0)
    metal = (m.group(3) or '').lower()
    qty = float(m.group(4) or 1)
    return (unit_oz, metal, qty)


def _parse_decimal_match(m: re.Match) -> Tuple[float, str, float]:
    """Parse decimal oz pattern: 1.5 oz silver (3)."""
    unit_oz = float(m.group(1))
    metal = (m.group(2) or '').lower()
    qty = float(m.group(3) or 1)
    return (unit_oz, metal, qty)


def _parse_grams_match(m: re.Match) -> Tuple[float, str, float]:
    """Parse grams pattern: 31.1 g gold (5)."""
    unit_oz = float(m.group(1)) / G_PER_OZ
    metal = (m.group(3) or '').lower()
    qty = float(m.group(4) or 1)
    return (unit_oz, metal, qty)


# Weight pattern parsers: maps pattern type to parser function
_WEIGHT_PARSERS = {
    'frac': _parse_frac_match,
    'decimal': _parse_decimal_match,
    'grams': _parse_grams_match,
}


def _parse_weight_match(
    m: re.Match, pattern_type: str
) -> Optional[Tuple[float, str, float]]:
    """Parse a weight regex match into (unit_oz, metal, qty). Returns None on error."""
    parser = _WEIGHT_PARSERS.get(pattern_type)
    if not parser:
        return None
    try:
        return parser(m)
    except (ValueError, IndexError):
        return None


def extract_basic_line_items(text: str) -> Tuple[List[LineItem], List[str]]:
    """Basic line item extraction shared across vendors."""
    items: List[LineItem] = []
    t = normalize_unicode(text or '')
    lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]

    for idx, ln in enumerate(lines):
        for pat, ptype in _WEIGHT_PATTERNS:
            for m in pat.finditer(ln):
                parsed = _parse_weight_match(m, ptype)
                if parsed:
                    unit_oz, metal, qty = parsed
                    items.append(LineItem(metal=metal, unit_oz=unit_oz, qty=qty, idx=idx))

    return items, lines


def dedupe_line_items(items: List[LineItem]) -> List[LineItem]:
    """Deduplicate items by (unit_oz, idx), keeping larger quantities."""
    if not items:
        return items

    buckets: Dict[Tuple[int, int], LineItem] = {}
    for it in items:
        ukey = int(round(it.unit_oz * 1000))
        k = (ukey, it.idx)
        cur = buckets.get(k)
        if not cur:
            buckets[k] = it
        else:
            if it.qty > cur.qty:
                cur.qty = it.qty
            if it.metal and not cur.metal:
                cur.metal = it.metal
    return list(buckets.values())


def _bundle_qty_from_match(m: re.Match) -> Optional[float]:
    """Scan a bundle-pattern match's groups for the first value in the valid bundle-qty range."""
    for g in range(1, len(m.groups()) + 1):
        val = m.group(g)
        if not (val and val.isdigit()):
            continue
        n = int(val)
        if 2 <= n <= 200:
            return float(n)
    return None


def _extract_bundle_qty_from_pattern(ln: str) -> Optional[float]:
    """Extract bundle quantity from a line using regex patterns."""
    for pat in BUNDLE_PATTERNS:
        m = pat.search(ln)
        if not m:
            continue
        qty = _bundle_qty_from_match(m)
        if qty is not None:
            return qty
    return None


def _extract_bundle_qty_from_sku(
    ln: str, sku_map: Dict[str, float]
) -> Optional[float]:
    """Extract bundle quantity from SKU mapping."""
    m_sku = PAT_SKU.search(ln)
    if m_sku and m_sku.group(1) in sku_map:
        return sku_map[m_sku.group(1)]
    return None


def find_bundle_qty(ctx: BundleSearchContext) -> Optional[float]:
    """Find bundle quantity from patterns or SKU mapping."""
    for _, ln in iter_nearby_lines(ctx.lines, ctx.idx, ctx.window):
        # Check bundle patterns first
        qty = _extract_bundle_qty_from_pattern(ln)
        if qty:
            return qty

        # Check SKU mapping if available
        if ctx.sku_map:
            qty = _extract_bundle_qty_from_sku(ln, ctx.sku_map)
            if qty:
                return qty

    return None


def _parse_price_amount(m: re.Match) -> Optional[float]:
    """Parse price amount from regex match, handling commas."""
    try:
        return float(m.group(2).replace(",", ""))
    except (ValueError, IndexError):
        return None


def _classify_price_kind(ln: str) -> str:
    """Classify price as 'unit', 'total', or 'unknown' based on context."""
    low = ln.lower()
    if _PAT_UNIT.search(low):
        return 'unit'
    if _PAT_TOTAL.search(low):
        return 'total'
    return 'unknown'


def extract_price_from_lines(ctx: PriceSearchContext) -> Optional[PriceHit]:
    """Shared price extraction logic used by multiple vendors."""
    ban = ctx.ban_pattern or DEFAULT_PRICE_BAN
    lb, ub = get_price_band(ctx.metal, ctx.unit_oz)

    for _, ln in iter_nearby_lines(ctx.lines, ctx.idx, ctx.window, ctx.forward_only):
        if ban.search(ln):
            continue

        m = MONEY_PATTERN.search(ln)
        if not m:
            continue

        amt = _parse_price_amount(m)
        if amt is None or not (lb <= amt <= ub):
            continue

        kind = _classify_price_kind(ln)
        return PriceHit(amount=amt, kind=kind)

    return None


def _enhance_item_qty(
    item: LineItem, lines: List[str], check_bundle: bool = True
) -> None:
    """Enhance item quantity by finding explicit qty or bundle patterns."""
    if not math.isclose(item.qty, 1.0):
        return

    # Try to find explicit quantity first
    eq = find_qty_near(lines, item.idx)
    if eq:
        item.qty = eq
        return

    # For ~1oz items, check for bundle quantity
    if check_bundle and 0.98 <= item.unit_oz <= 1.02:
        ctx = BundleSearchContext(lines=lines, idx=item.idx, sku_map=SKU_BUNDLE_MAP)
        bq = find_bundle_qty(ctx)
        if bq:
            item.qty = bq
