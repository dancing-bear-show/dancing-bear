"""
Extract per-order cost per ounce from Gmail order emails (TD Precious Metals and Costco).

Outputs a CSV with: vendor,date,metal,currency,cost_total,cost_per_oz,order_id,subject

Heuristics:
- Deduplicates by order id, keeping the latest email per order.
- For TD emails, tries to parse 'Total' or 'Subtotal' currency amounts.
- Computes cost_per_oz = cost_total / total_oz (sum of all line items in the order for that metal).
- If an order mixes metals, computes a row per metal using the same order total (note: this can
  over-approximate if costs differ by metal; most orders contain a single metal).

Usage:
  python -m metals.costs --profile gmail_personal --out out/metals/costs.csv
"""
from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from core.text_utils import normalize_unicode
from mail.config_resolver import resolve_paths_profile
from mail.gmail_api import GmailClient

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
from .costs_common import (
    extract_order_amount,
    find_money,
    format_breakdown,
    format_qty,
    write_costs_csv,
)
from .cost_extractor import CostExtractor, MessageInfo, OrderData
from .vendors import DEFAULT_PRICE_BAN, GMAIL_VENDORS, get_vendor_for_sender


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
class OrderRowData:
    """Data for building order output rows."""
    oid: str
    vendor: str
    subject: str
    cur: str
    dt: str
    oz_by_metal: Dict[str, float]
    units_by_metal: Dict[str, Dict[float, float]]
    cost_alloc: Dict[str, float]
    alloc_strategy: str


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


def _unit_oz_override_near(lines: List[str], idx: int, metal_ctx: str) -> float | None:
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


def _extract_line_items(text: str) -> Tuple[List[Dict], List[str]] | None:
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
                    unit_oz=unit_oz, metal=metal, qty=qty, explicit_qty=explicit_qty
                )
                qty, unit_oz = _apply_qty_heuristics(ctx)
                items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})
    return items, lines


def _build_uoz_patterns(unit_oz: float | None) -> Tuple[re.Pattern[str] | None, List[str]]:
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


def _try_anchored_extraction(ctx: ExtractionContext) -> Tuple[str, float, str] | None:
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
    before_amt = ctx.lower[max(0, m_money.start()-80):m_money.start()]
    has_qty = bool(re.search(r"(?i)\bx\s*\d{1,3}\b", before_amt) or
                   re.search(r"(?i)\bqty(?:uantity)?\s*:?\s*\d{1,3}\b", before_amt))
    if has_qty and not _PAT_UNIT_PRICE.search(tail):
        kind = 'total' if ctx.vendor == 'td' else 'unit'
    return cur, amt, kind


def _determine_price_kind(lower: str, has_uoz_here: bool, has_uoz_neighbor: bool) -> Tuple[str, bool, bool]:
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


def _check_uoz_in_neighbors(lines: List[str], j: int, uoz_pat: re.Pattern[str] | None) -> bool:
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


def _is_valid_price_line(
    has_metal: bool,
    has_uoz_here: bool,
    has_uoz_neighbor: bool,
    mentions_price: bool,
    mentions_total: bool,
    kind: str
) -> bool:
    """Check if this line should be considered a valid price line.

    Args:
        has_metal: Line contains metal keyword.
        has_uoz_here: Line contains unit-oz pattern.
        has_uoz_neighbor: Neighbor lines contain unit-oz pattern.
        mentions_price: Line mentions price-related keywords.
        mentions_total: Line mentions "total".
        kind: Determined price kind.

    Returns:
        True if line is valid for price extraction.
    """
    # Skip if mentions "total" but kind isn't "total"
    if mentions_total and kind != "total":
        return False

    # Accept if line has metal, unit-oz, or price keywords
    return has_metal or has_uoz_here or has_uoz_neighbor or mentions_price


def _process_candidate_line(
    ln: str,
    lower: str,
    lines: List[str],
    j: int,
    metal: str,
    uoz_pat: re.Pattern[str] | None,
) -> Tuple[str, float, str] | None:
    """Process a single candidate line for price extraction.

    Returns:
        (currency, amount, kind) if valid price found, else None.
    """
    if DEFAULT_PRICE_BAN.search(ln):
        return None

    has_uoz_here = bool(uoz_pat and uoz_pat.search(lower))
    has_uoz_neighbor = _check_uoz_in_neighbors(lines, j, uoz_pat)

    money = find_money(ln)
    if not money:
        return None

    want = (metal or "").lower()
    has_metal = bool(want and want in lower)
    kind, mentions_price, mentions_total = _determine_price_kind(lower, has_uoz_here, has_uoz_neighbor)

    if _is_valid_price_line(has_metal, has_uoz_here, has_uoz_neighbor, mentions_price, mentions_total, kind):
        return money[0], money[1], kind

    return None


def _extract_amount_near_line(
    lines: List[str], idx: int, metal: str, unit_oz: float | None = None, vendor: str | None = None
) -> Tuple[str, float, str] | None:
    """Return (currency, amount, kind) if a price appears near the line.

    Heuristics:
    - Search a wider window around the item line (idx ± 12), prioritizing closer lines first.
    - Accept lines containing the metal keyword, or the exact unit-oz text, or price-related keywords.
    - Avoid global order totals: still ban 'subtotal', 'shipping', 'tax', 'order number'.
      Allow 'total' only when 'price' or a unit-oz mention is present (to pick up line 'Total Price').
    - kind ∈ {unit,total,unknown}; caller uses kind to decide whether to multiply by quantity.
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
                uoz_texts=uoz_texts, vendor=vendor_lower
            )
            result = _try_anchored_extraction(extraction_ctx)
            if result:
                return result

        # Try general price extraction
        result = _process_candidate_line(ln, lower, lines, j, metal, uoz_pat)
        if result:
            return result

    return None


def _classify_vendor(from_header: str) -> str:
    """Classify vendor from email sender using vendor parsers."""
    vendor = get_vendor_for_sender(from_header, GMAIL_VENDORS)
    return vendor.name if vendor else 'Other'


def _is_order_confirmation(subject: str, from_header: str) -> bool:
    """Check if email is an order confirmation based on subject and sender."""
    s = (subject or '').lower()
    f = (from_header or '').lower()
    if 'td' in f and 'order confirmation' in s:
        return True
    if 'costco' in f and 'your costco.ca order number' in s:
        return True
    return 'order confirmation' in s


_CANCELLED_PAT = re.compile(r"(?i)\bcancel(?:led|ed)\b")


def _is_cancelled(subject: str, from_header: str) -> bool:
    """Check if order was cancelled based on subject and sender."""
    s = f"{subject or ''} {from_header or ''}"
    return _CANCELLED_PAT.search(s) is not None


_ORDER_PAT = re.compile(r"(?i)order\s*(?:number|#)?\s*[:#]?\s*(\d{6,})")
_COSTCO_ORDER_PAT = re.compile(r"(?i)costco\.ca\s+order\D*(\d{6,})")
_PAT_UNIT_PRICE = re.compile(r"(?i)\b(unit|each|ea|per)\b")

_QUERIES = [
    'from:noreply@td.com subject:"TD Precious Metals"',
    'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
    'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
    '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)',
    'cancel from:orderstatus@costco.ca',
    'cancel from:order-cancel@costco.ca',
]


def _fetch_message_ids(client: GmailClient) -> List[str]:
    """Fetch and deduplicate message IDs from all vendor queries."""
    ids: List[str] = []
    for q in _QUERIES:
        ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
    return list(dict.fromkeys(ids))


def _group_messages_by_order(client: GmailClient, ids: List[str]) -> Dict[str, List[Tuple[str, int, str, str]]]:
    """Group messages by order ID. Returns {order_id: [(msg_id, recv_ms, subject, from_header), ...]}."""
    by_order: Dict[str, List[Tuple[str, int, str, str]]] = {}
    for mid in ids:
        msg = client.get_message(mid, fmt='full')
        hdrs = GmailClient.headers_to_dict(msg)
        subject = hdrs.get('subject', '')
        text = client.get_message_text(mid)
        m = _ORDER_PAT.search(subject) or _ORDER_PAT.search(text) or _COSTCO_ORDER_PAT.search(subject)
        oid = m.group(1) if m else mid
        recv_ms = int(msg.get('internalDate') or 0)
        by_order.setdefault(oid, []).append((mid, recv_ms, subject or '', hdrs.get('from', '')))
    return by_order


def _compute_line_costs(
    final_qty: Dict[Tuple[str, float], float],
    price_hits: Dict[Tuple[str, float], List[Tuple[float, str]]],
    vendor: str
) -> Dict[str, float]:
    """Compute line-item costs per metal from price hits."""
    line_cost: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
    for (metal, uoz), qty in final_qty.items():
        hits = price_hits.get((metal, uoz), [])
        if not hits:
            continue
        amt_total = next((a for (a, k) in hits if k == 'total'), None)
        if amt_total is not None:
            line_cost[metal] += float(amt_total)
        else:
            unit_vals = [a for (a, k) in hits if k in ('unit', 'unknown')]
            if unit_vals:
                val = max(unit_vals)
                if vendor == 'Costco' and metal == 'silver' and uoz <= 1.05 and qty >= 10 and (val / max(uoz, 1e-6)) > 150:
                    line_cost[metal] += float(val)
                else:
                    line_cost[metal] += float(val) * max(qty, 1.0)
    return line_cost


def _allocate_costs(
    oz_by_metal: Dict[str, float],
    line_cost: Dict[str, float],
    total: float,
    vendor: str
) -> Tuple[Dict[str, float], str]:
    """Allocate costs to metals. Returns (cost_alloc, alloc_strategy)."""
    metals_present = [m for m in ('gold', 'silver') if oz_by_metal.get(m, 0.0) > 0]
    use_line = any(v > 0 for v in line_cost.values())

    if vendor == 'TD' and total and oz_by_metal.get('gold', 0.0) > 0 and oz_by_metal.get('silver', 0.0) > 0:
        rem = total - (line_cost.get('gold', 0.0) + line_cost.get('silver', 0.0))
        if rem > 0.01:
            line_cost['silver'] += rem

    if len(metals_present) == 1 and total:
        return {'gold': 0.0, 'silver': 0.0, metals_present[0]: total}, 'order-single-metal'
    if use_line:
        return line_cost.copy(), 'line-item'
    denom = sum(oz_by_metal[m] for m in metals_present)
    alloc = {m: (total * (oz_by_metal[m] / denom)) if denom > 0 else 0.0 for m in ('gold', 'silver')}
    return alloc, 'order-proportional'


def _build_order_rows(data: OrderRowData) -> List[Dict[str, str | float]]:
    """Build output rows for an order."""
    rows: List[Dict[str, str | float]] = []
    for metal in ('gold', 'silver'):
        oz = data.oz_by_metal.get(metal, 0.0)
        if oz <= 0:
            continue
        alloc = data.cost_alloc.get(metal, 0.0)
        cpo = alloc / oz
        metal_units = data.units_by_metal.get(metal, {})
        cur_out = 'C$' if data.vendor in ('TD', 'Costco') else (data.cur or 'C$')
        rows.append({
            'vendor': data.vendor, 'date': data.dt, 'metal': metal, 'currency': cur_out,
            'cost_total': round(alloc, 2), 'cost_per_oz': round(cpo, 2),
            'order_id': data.oid, 'subject': data.subject, 'total_oz': round(oz, 3),
            'unit_count': format_qty(sum(metal_units.values())),
            'units_breakdown': format_breakdown(metal_units), 'alloc': data.alloc_strategy,
        })
    return rows


def _extract_items_from_message(
    client: GmailClient,
    mid: str,
    from_header: str,
    price_hits: Dict[Tuple[str, float], List[Tuple[float, str]]]
) -> Dict[Tuple[str, float], float]:
    """Extract line items and prices from a single message.

    Args:
        client: Gmail client.
        mid: Message ID.
        from_header: From header for vendor classification.
        price_hits: Dictionary to accumulate price hits (modified in-place).

    Returns:
        Quantity map {(metal, unit_oz): qty}.
    """
    text = client.get_message_text(mid)
    result = _extract_line_items(text)
    if not result:
        return {}

    items, _ = result
    qmap: Dict[Tuple[str, float], float] = {}
    lines_msg = [ln.strip() for ln in (text or '').splitlines() if ln.strip()]

    for it in items:
        metal, unit_oz = str(it.get('metal')), float(it.get('unit_oz') or 0.0)
        qty = float(it.get('qty') or 1.0)
        key = (metal, round(unit_oz, 4))
        qmap[key] = qmap.get(key, 0.0) + qty

        hit = _extract_amount_near_line(
            lines_msg, int(it.get('idx') or 0), metal, unit_oz, _classify_vendor(from_header)
        )
        if hit:
            price_hits.setdefault(key, []).append((float(hit[1]), str(hit[2])))

    return qmap


def _process_messages(
    client: GmailClient,
    msgs: List[Tuple[str, int, str, str]]
) -> Tuple[Dict[Tuple[str, float], float], Dict[Tuple[str, float], List[Tuple[float, str]]], Tuple[str, float] | None, int]:
    """Process all messages for an order.

    Args:
        client: Gmail client.
        msgs: List of (msg_id, recv_ms, subject, from_header).

    Returns:
        (final_qty, price_hits, amount_pref, latest_recv_ms).
    """
    qty_by_msg: List[Dict[Tuple[str, float], float]] = []
    price_hits: Dict[Tuple[str, float], List[Tuple[float, str]]] = {}
    latest_recv_ms = 0
    amount_pref: Tuple[str, float] | None = None

    # Prefer confirmation messages
    msgs_conf = [m for m in msgs if _is_order_confirmation(m[2], m[3])]
    msgs_use = msgs_conf if msgs_conf else msgs

    for mid, recv_ms, _, from_here in msgs_use:
        latest_recv_ms = max(latest_recv_ms, recv_ms)
        qmap = _extract_items_from_message(client, mid, from_here, price_hits)
        if qmap:
            qty_by_msg.append(qmap)

        # Extract order total
        text = client.get_message_text(mid)
        amt = extract_order_amount(text)
        if amt and (amount_pref is None or amt[1] > amount_pref[1]):
            amount_pref = amt

    # Merge quantities (use max across messages)
    final_qty: Dict[Tuple[str, float], float] = {}
    for qmap in qty_by_msg:
        for key, q in qmap.items():
            final_qty[key] = max(final_qty.get(key, 0.0), q)

    return final_qty, price_hits, amount_pref, latest_recv_ms


def _aggregate_metals(final_qty: Dict[Tuple[str, float], float]) -> Tuple[Dict[str, float], Dict[str, Dict[float, float]]]:
    """Aggregate quantities by metal type.

    Args:
        final_qty: Final quantities {(metal, unit_oz): qty}.

    Returns:
        (oz_by_metal, units_by_metal).
    """
    oz_by_metal: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
    units_by_metal: Dict[str, Dict[float, float]] = {'gold': {}, 'silver': {}}

    for (metal, uoz), qty in final_qty.items():
        if metal in oz_by_metal:
            oz_by_metal[metal] += uoz * qty
            units_by_metal[metal][uoz] = units_by_metal[metal].get(uoz, 0.0) + qty

    return oz_by_metal, units_by_metal


def _process_order(
    client: GmailClient, oid: str, msgs: List[Tuple[str, int, str, str]]
) -> List[Dict[str, str | float]]:
    """Process a single order and return its output rows."""
    # Skip cancelled orders
    if any(_is_cancelled(m[2], m[3]) for m in msgs):
        return []

    # Extract items and prices from all messages
    final_qty, price_hits, amount_pref, latest_recv_ms = _process_messages(client, msgs)
    if not final_qty:
        return []

    # Get order metadata from first message
    msg0 = client.get_message(msgs[0][0], fmt='full')
    hdrs = GmailClient.headers_to_dict(msg0)
    subject, vendor = hdrs.get('subject', ''), _classify_vendor(hdrs.get('from', ''))

    # Aggregate metals
    oz_by_metal, units_by_metal = _aggregate_metals(final_qty)

    # Compute costs
    cur, total = amount_pref if amount_pref else ('', 0.0)
    line_cost = _compute_line_costs(final_qty, price_hits, vendor)
    cost_alloc, alloc_strategy = _allocate_costs(oz_by_metal, line_cost, total, vendor)

    # Format date
    dt = datetime.fromtimestamp(latest_recv_ms / 1000.0, tz=timezone.utc).astimezone().date().isoformat()

    # Build output rows
    row_data = OrderRowData(
        oid=oid, vendor=vendor, subject=subject, cur=cur, dt=dt,
        oz_by_metal=oz_by_metal, units_by_metal=units_by_metal,
        cost_alloc=cost_alloc, alloc_strategy=alloc_strategy
    )
    return _build_order_rows(row_data)


class GmailCostExtractor(CostExtractor):
    """Extract precious metals costs from Gmail order emails."""

    def __init__(self, profile: str, out_path: str, days: int = 365):
        super().__init__(profile, out_path, days)
        self.client: GmailClient | None = None

    def _authenticate(self) -> None:
        """Authenticate with Gmail."""
        cred, tok = resolve_paths_profile(arg_credentials=None, arg_token=None, profile=self.profile)
        self.client = GmailClient(credentials_path=cred, token_path=tok, cache_dir='.cache')
        self.client.authenticate()

    def _fetch_message_ids(self) -> List[str]:
        """Fetch message IDs from Gmail."""
        return _fetch_message_ids(self.client)

    def _get_message_info(self, msg_id: str) -> MessageInfo:
        """Get normalized message information."""
        msg = self.client.get_message(msg_id, fmt='full')
        hdrs = GmailClient.headers_to_dict(msg)
        text = self.client.get_message_text(msg_id)
        recv_ms = int(msg.get('internalDate') or 0)

        return MessageInfo(
            msg_id=msg_id,
            subject=hdrs.get('subject', ''),
            from_header=hdrs.get('from', ''),
            body_text=text,
            received_date='',  # Not used for Gmail (uses received_ms)
            received_ms=recv_ms
        )

    def _extract_order_id(self, msg: MessageInfo) -> Optional[str]:
        """Extract order ID from message."""
        m = _ORDER_PAT.search(msg.subject) or _ORDER_PAT.search(msg.body_text) or \
            _COSTCO_ORDER_PAT.search(msg.subject)
        return m.group(1) if m else msg.msg_id

    def _select_best_message(self, messages: List[MessageInfo]) -> MessageInfo:
        """Select best message (prefer confirmation)."""
        conf_msgs = [m for m in messages if _is_order_confirmation(m.subject, m.from_header)]
        return conf_msgs[0] if conf_msgs else messages[0]

    def _classify_vendor(self, from_header: str) -> str:
        """Classify vendor from sender."""
        vendor = get_vendor_for_sender(from_header, GMAIL_VENDORS)
        return vendor.name if vendor else 'Other'

    def _process_order_to_rows(self, order: OrderData) -> List[Dict[str, str | float]]:
        """Process a single order into output rows."""
        # Convert MessageInfo list back to format expected by _process_order
        msgs_tuple = [
            (m.msg_id, m.received_ms, m.subject, m.from_header)
            for m in order.messages
        ]
        return _process_order(self.client, order.order_id, msgs_tuple)

    def run(self) -> int:
        """Run Gmail cost extraction (override to use write_costs_csv)."""
        self._authenticate()
        ids = self._fetch_message_ids()

        if not ids:
            print('no messages found')
            return 0

        by_order = self._group_by_order(ids)

        if not by_order:
            print('no orders found')
            return 0

        out_rows: List[Dict[str, str | float]] = []
        for oid, messages in by_order.items():
            order = self._build_order_data(oid, messages)
            rows = self._process_order_to_rows(order)
            out_rows.extend(rows)

        if out_rows:
            write_costs_csv(self.out_path, out_rows)
            print(f"wrote {self.out_path} rows={len(out_rows)}")
        else:
            print('messages found but no costs extracted')

        return 0


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Extract costs and cost-per-oz from Gmail order emails')
    p.add_argument('--profile', default='gmail_personal')
    p.add_argument('--out', default='out/metals/costs.csv')
    args = p.parse_args(argv)

    extractor = GmailCostExtractor(
        profile=getattr(args, 'profile', 'gmail_personal'),
        out_path=getattr(args, 'out', 'out/metals/costs.csv'),
        days=365
    )
    return extractor.run()


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
