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
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from core.text_utils import normalize_unicode
from mail.config_resolver import resolve_paths_profile
from mail.gmail_api import GmailClient

from .costs_common import (
    G_PER_OZ,
    MONEY_PATTERN,
    extract_order_amount,
    find_money,
    format_breakdown,
    format_qty,
    write_costs_csv,
)
from .vendors import GMAIL_VENDORS, get_vendor_for_sender


# SKU-based mappings for bundle sizes and unit-oz overrides
_SKU_BUNDLE_MAP = {'3796875': 25.0}  # 25 x 1 oz tube (Costco)
_SKU_UNIT_MAP_SILVER = {'2796876': 10.0}  # 10 oz silver bar
_SKU_UNIT_MAP_GOLD = {'5882020': 0.25}  # 1/4 oz Canadian Gold Maple Leaf (Costco)
_PHRASE_MAP_SILVER = {'magnificent maple leaves silver coin': 10.0}

# Compiled regex patterns for line item extraction
_PAT_FRAC = re.compile(r"(?i)\b(\d+)\s*/\s*(\d+)\s*oz\b[^\n]*?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?")
_PAT_OZ = re.compile(r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*oz\b[^\n]*?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?")
_PAT_G = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b[^\n]*?\b(gold|silver)\b(?:(?:(?!\n).)*?\bx\s*(\d+))?")
_PAT_QTY_LIST = [
    re.compile(r"(?i)\bqty\s*:?\s*(\d{1,3})\b"),
    re.compile(r"(?i)\bquantity\s*:?\s*(\d{1,3})\b"),
    re.compile(r"(?i)\bx\s*(\d{1,3})\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*x\b"),
]
_PAT_BUNDLE_LIST = [
    re.compile(r"(?i)\b(\d{1,3})\s*[- ]?pack\b"),
    re.compile(r"(?i)\bpack\s*of\s*(\d{1,3})\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*coins?\b"),
    re.compile(r"(?i)\b(\d{1,3})\s*ct\b"),
    re.compile(r"(?i)\b(roll|tube)\s*of\s*(\d{1,3})\b"),
]
_PAT_ITEM_SKU = re.compile(r"(?i)\bitem(?:\s*(?:#|number)\s*)?:?\s*(\d{5,})\b")
_PAT_LEADING_QTY = re.compile(r"(?i)\b(\d{1,3})\s*x\b")


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


def _unit_oz_override_near(lines: List[str], idx: int, metal_ctx: str) -> float | None:
    """Map item numbers/phrases to unit-oz when emails omit explicit size."""
    metal_key = (metal_ctx or '').strip().lower()
    sku_unit_map = _SKU_UNIT_MAP_SILVER if metal_key == 'silver' else _SKU_UNIT_MAP_GOLD
    phrase_map = _PHRASE_MAP_SILVER if metal_key == 'silver' else {}
    for j in (idx, idx + 1, idx - 1, idx + 2):
        if 0 <= j < len(lines):
            s = lines[j]
            m_item = _PAT_ITEM_SKU.search(s or '')
            if m_item and m_item.group(1) in sku_unit_map:
                return sku_unit_map[m_item.group(1)]
            s_low = (s or '').lower()
            for ph, uoz in phrase_map.items():
                if ph in s_low:
                    return uoz
    return None


def _apply_qty_heuristics(
    lines: List[str], ln: str, m: re.Match[str], idx: int, unit_oz: float, metal: str, qty: float, explicit_qty: bool
) -> Tuple[float, float]:
    """Apply quantity and unit-oz heuristics. Returns (qty, unit_oz)."""
    if math.isclose(qty, 1.0) and not explicit_qty:
        pre = ln[max(0, m.start() - 120):m.start()]
        mpre = _PAT_LEADING_QTY.search(pre)
        pre_q = float(mpre.group(1)) if mpre else None
        eq = _explicit_qty_near(lines, idx)
        if eq:
            if pre_q and (0.98 <= unit_oz <= 1.02) and eq < pre_q:
                qty = pre_q
            else:
                qty = eq
        elif pre_q:
            qty = pre_q
        else:
            bq = _bundle_qty_near(lines, idx)
            if bq and (0.98 <= unit_oz <= 1.02):
                qty = bq
    uov = _unit_oz_override_near(lines, idx, metal)
    if uov:
        unit_oz = uov
    return qty, unit_oz


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
    for idx, ln in enumerate(lines):
        for m in _PAT_FRAC.finditer(ln):
            num, den = float(m.group(1)), float(m.group(2) or 1)
            metal = (m.group(3) or '').lower()
            qty = float(m.group(4) or 1)
            explicit_qty = m.group(4) is not None
            unit_oz = num / max(den, 1.0)
            qty, unit_oz = _apply_qty_heuristics(lines, ln, m, idx, unit_oz, metal, qty, explicit_qty)
            items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})
        for m in _PAT_OZ.finditer(ln):
            unit_oz = float(m.group(1))
            metal = (m.group(2) or '').lower()
            qty = float(m.group(3) or 1)
            explicit_qty = m.group(3) is not None
            qty, unit_oz = _apply_qty_heuristics(lines, ln, m, idx, unit_oz, metal, qty, explicit_qty)
            items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})
        for m in _PAT_G.finditer(ln):
            wt_g = float(m.group(1))
            metal = (m.group(3) or '').lower()
            qty = float(m.group(4) or 1)
            explicit_qty = m.group(4) is not None
            unit_oz = wt_g / G_PER_OZ
            qty, unit_oz = _apply_qty_heuristics(lines, ln, m, idx, unit_oz, metal, qty, explicit_qty)
            items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})
    return items, lines


_BAN_ALWAYS_PAT = re.compile(r"(?i)\b(subtotal|shipping|tax|order number|order #)\b")


def _extract_amount_near_line(
    lines: List[str], idx: int, metal: str, unit_oz: float | None = None, vendor: str | None = None
) -> Tuple[str, float, str] | None:
    """Return (currency, amount, kind) if a price appears near the line.

    Heuristics:
    - Search a wider window around the item line (idx ± 4), prioritizing closer lines first.
    - Accept lines containing the metal keyword, or the exact unit-oz text, or price-related keywords.
    - Avoid global order totals: still ban 'subtotal', 'shipping', 'tax', 'order number'.
      Allow 'total' only when 'price' or a unit-oz mention is present (to pick up line 'Total Price').
    - kind ∈ {unit,total,unknown}; caller uses kind to decide whether to multiply by quantity.
    """
    want = (metal or "").lower()
    uoz_pat = None
    if unit_oz and unit_oz > 0:
        u = int(unit_oz) if abs(unit_oz - int(unit_oz)) < 1e-6 else unit_oz
        uoz_pat = re.compile(rf"(?i)\b{u}\s*oz\b")

    # Candidate indices ordered by proximity
    # Build a proximity-ordered window up to ±12 lines
    candidates = [idx]
    for d in range(1, 13):
        candidates.extend([idx + d, idx - d])
    for j in candidates:
        if 0 <= j < len(lines):
            ln = lines[j] or ""
            lower = ln.lower()
            # Try an anchored extraction on the same line to handle compact table-in-one-line cases
            # Enable for TD and Costco with proximity and keyword guards to avoid totals
            use_anchored = (vendor or '').strip().lower() in ('td', 'costco')
            if use_anchored:
                # Build possible textual representations of the unit size
                uoz_texts = []
                if unit_oz and unit_oz > 0:
                    # decimal form (e.g., '1 oz')
                    u_dec = int(unit_oz) if abs(unit_oz - int(unit_oz)) < 1e-6 else unit_oz
                    uoz_texts.append(fr"\b{u_dec}\s*oz\b")
                    # fraction form (e.g., '1/10 oz') when applicable
                    if unit_oz < 1.0:
                        inv = 1.0 / unit_oz
                        inv_i = int(round(inv))
                        if inv_i >= 2 and abs(inv - inv_i) < 1e-3 and inv_i <= 100:
                            uoz_texts.append(fr"\b1\s*/\s*{inv_i}\s*oz\b")
                    metal_kw = (metal or '').strip().lower()
                    if uoz_texts and metal_kw in ('gold', 'silver'):
                        uoz_alt = "|".join(uoz_texts)
                        # Allow either ordering: 'uoz ... metal' or 'metal ... uoz'
                        anch1 = re.search(fr"(?i)({uoz_alt}).{{0,200}}?\b{metal_kw}\b", ln)
                        anch2 = re.search(fr"(?i)\b{metal_kw}\b.{{0,200}}?({uoz_alt})", ln)
                        anch = anch1 or anch2
                    if anch:
                        anchor_end = anch.end()
                        # From the end of the anchor, find the first currency
                        m_money = MONEY_PATTERN.search(ln, pos=anchor_end)
                        if m_money:
                            # Reject if the currency is very far away (likely picking up order totals)
                            if (m_money.start() - anchor_end) > 80:
                                pass
                            else:
                                # Ensure we didn't step into a totals/summary region before the amount
                                between = lower[anchor_end:m_money.start()]
                                if re.search(r"(?i)\b(subtotal|shipping|tax|total)\b", between):
                                    pass
                                else:
                                    cur = m_money.group(1).upper()
                                    amt = float(m_money.group(2).replace(',', ''))
                                    # Determine kind heuristically from keywords near the money
                                    tail = lower[anchor_end: m_money.end()]
                                    kind = 'unit' if re.search(r"(?i)\b(unit|each|ea|per)\b", tail) else 'unknown'
                                    # Quantity indicator heuristic (vendor-specific):
                                    # - TD emails typically place the extended line total after "x N"
                                    # - Costco emails often show unit price next to "x N" without 'each'
                                    before_amt = lower[max(0, m_money.start()-80):m_money.start()]
                                    has_qty = bool(re.search(r"(?i)\bx\s*\d{1,3}\b", before_amt) or re.search(r"(?i)\bqty(?:uantity)?\s*:?\s*\d{1,3}\b", before_amt))
                                    if has_qty and not re.search(r"(?i)\b(unit|each|ea|per)\b", tail):
                                        if (vendor or '').lower() == 'td':
                                            kind = 'total'
                                        elif (vendor or '').lower() == 'costco':
                                            kind = 'unit'
                                    return cur, amt, kind

            # If no anchored hit, apply generic rules
            if _BAN_ALWAYS_PAT.search(ln):
                continue
            has_uoz_here = bool(uoz_pat and uoz_pat.search(lower))
            # Also consider immediate neighbor for unit-oz mention
            has_uoz_neighbor = False
            for k in (j - 1, j + 1):
                if 0 <= k < len(lines):
                    if uoz_pat and uoz_pat.search((lines[k] or "").lower()):
                        has_uoz_neighbor = True
                        break

            money = find_money(ln)
            if not money:
                continue

            has_metal = bool(want and want in lower)
            mentions_price = bool(re.search(r"(?i)\b(price|unit|each|ea|per)\b", lower))
            mentions_total = bool(re.search(r"(?i)\btotal\b", lower))

            # Determine kind
            kind = "unknown"
            if re.search(r"(?i)\b(unit|each|ea|per)\b", lower):
                kind = "unit"
            elif re.search(r"(?i)\b(total\s*price|line\s*total|item\s*total)\b", lower):
                kind = "total"
            elif mentions_total and (mentions_price or has_uoz_here or has_uoz_neighbor):
                # Treat 'Total ...' near the item as a line total when tied to the unit size context
                kind = "total"

            # Acceptance rules
            if has_metal or has_uoz_here or has_uoz_neighbor or mentions_price:
                # Do not accept bare 'Total' lines unless tied to price context
                if mentions_total and kind != "total":
                    # likely an order total; skip
                    continue
                cur, amt = money
                return cur, amt, kind
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


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='Extract costs and cost-per-oz from Gmail order emails')
    p.add_argument('--profile', default='gmail_personal')
    p.add_argument('--out', default='out/metals/costs.csv')
    args = p.parse_args(argv)

    cred, tok = resolve_paths_profile(arg_credentials=None, arg_token=None, profile=getattr(args, 'profile', None))
    client = GmailClient(credentials_path=cred, token_path=tok, cache_dir='.cache')
    client.authenticate()

    queries = [
        # TD confirmations / notifications
        'from:noreply@td.com subject:"TD Precious Metals"',
        'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
        # Costco confirmations / shipped
        'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
        # Royal Canadian Mint confirmations / receipts / shipping
        '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)',
        # Cancellation notices (Costco)
        'cancel from:orderstatus@costco.ca',
        'cancel from:order-cancel@costco.ca',
    ]
    ids: List[str] = []
    for q in queries:
        ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
    ids = list(dict.fromkeys(ids))

    # Group messages by order id (include all messages for better line coverage)
    # Track messages per order id, keeping message id, receive time, subject and from header
    by_order: Dict[str, List[Tuple[str, int, str, str]]] = {}
    order_pat = re.compile(r"(?i)order\s*(?:number|#)?\s*[:#]?\s*(\d{6,})")
    for mid in ids:
        msg = client.get_message(mid, fmt='full')
        hdrs = GmailClient.headers_to_dict(msg)
        subject = hdrs.get('subject', '')
        text = client.get_message_text(mid)
        m = order_pat.search(subject) or order_pat.search(text)
        if not m:
            # Fallback: scan for 7-12 digit number following 'Your Costco.ca Order'
            m = re.search(r"(?i)costco\.ca\s+order\D*(\d{6,})", subject)
        oid = m.group(1) if m else mid
        recv_ms = int(msg.get('internalDate') or 0)
        by_order.setdefault(oid, []).append((mid, recv_ms, subject or '', hdrs.get('from', '')))

    # Build CSV rows
    rows_out: List[Dict[str, str | float]] = []
    for oid, msgs in by_order.items():
        if any(_is_cancelled(m[2], m[3]) for m in msgs):
            continue
        # Aggregate line items across all messages for this order, de-duplicated across messages.
        # Track per-message quantities per (metal, unit_oz), then take the max across messages.
        qty_by_msg: List[Dict[Tuple[str, float], float]] = []
        price_hits: Dict[Tuple[str, float], List[Tuple[float, str]]] = {}
        latest_recv_ms = 0
        amount_pref: Tuple[str, float] | None = None
        # Prefer only the order-confirmation emails when present, else fall back to all
        msgs_conf = [m for m in msgs if _is_order_confirmation(m[2], m[3])]
        msgs_use = msgs_conf if msgs_conf else msgs
        for mid, recv_ms, subject_here, from_here in msgs_use:
            latest_recv_ms = max(latest_recv_ms, recv_ms)
            text = client.get_message_text(mid)
            items, lines_here = _extract_line_items(text)
            # Build per-message quantity map and gather price hits for this message
            qmap: Dict[Tuple[str, float], float] = {}
            lines_msg = [ln.strip() for ln in (text or '').splitlines() if ln.strip()]
            for it in items:
                metal = str(it.get('metal'))
                unit_oz = float(it.get('unit_oz') or 0.0)
                qty = float(it.get('qty') or 1.0)
                key = (metal, round(unit_oz, 4))
                qmap[key] = qmap.get(key, 0.0) + qty
                # Price hit near this item line (record; we'll choose the best later)
                idx_line = int(it.get('idx') or 0)
                hit = _extract_amount_near_line(lines_msg, idx_line, metal, unit_oz, _classify_vendor(from_here))
                if hit:
                    _, amt, kind = hit
                    L = price_hits.setdefault(key, [])
                    L.append((float(amt), str(kind)))
            qty_by_msg.append(qmap)
            amt = extract_order_amount(text)
            if amt and (amount_pref is None or amt[1] > amount_pref[1]):
                amount_pref = amt
        # Collapse quantities: take max across messages per key
        final_qty: Dict[Tuple[str, float], float] = {}
        for qmap in qty_by_msg:
            for key, q in qmap.items():
                final_qty[key] = max(final_qty.get(key, 0.0), q)
        if not final_qty:
            continue
        # Use the first message to extract headers (vendor/subject) for reporting
        first_mid = msgs[0][0]
        msg0 = client.get_message(first_mid, fmt='full')
        hdrs = GmailClient.headers_to_dict(msg0)
        subject = hdrs.get('subject', '')
        vendor = _classify_vendor(hdrs.get('from', ''))
        # Sum ounces and unit counts per metal across all messages
        oz_by_metal: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
        units_by_metal: Dict[str, Dict[float, float]] = {'gold': {}, 'silver': {}}
        for (metal, uoz), qty in final_qty.items():
            if metal not in oz_by_metal:
                continue
            oz_by_metal[metal] += uoz * qty
            units = units_by_metal[metal]
            units[uoz] = units.get(uoz, 0.0) + qty
        # Attempt line-item price capture across messages, using each item's own message lines
        line_cost_by_metal: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
        for (metal, uoz), qty in final_qty.items():
            hits = price_hits.get((metal, uoz), [])
            if not hits:
                continue
            # Prefer a 'total' hit if present; else 'unit' (unknown treated as unit)
            amt_total = next((a for (a,k) in hits if k=='total'), None)
            if amt_total is not None:
                line_cost_by_metal[metal] += float(amt_total)
            else:
                # Take the max unit/unknown price
                unit_vals = [a for (a,k) in hits if k in ('unit','unknown')]
                if unit_vals:
                    val = max(unit_vals)
                    # Heuristic correction: Costco silver 1 oz coins often show a line-total amount next to 'x N'.
                    # If interpreting as a unit price would imply an implausibly high per-oz price, treat as line total.
                    if (vendor == 'Costco' and metal == 'silver' and uoz <= 1.05 and qty >= 10 and (val / max(uoz, 1e-6)) > 150):
                        line_cost_by_metal[metal] += float(val)
                    else:
                        line_cost_by_metal[metal] += float(val) * max(qty, 1.0)

        # If we captured a trustworthy gold line but may have missed some silver line(s),
        # allocate any remaining order total to silver for TD orders with mixed metals.
        # This matches patterns like: "1/2 oz Gold ... x 1 C$2,548.10" + multiple silver lines.
        cur, total = (amount_pref if amount_pref else ('', 0.0))
        if vendor == 'TD' and total and oz_by_metal.get('gold', 0.0) > 0 and oz_by_metal.get('silver', 0.0) > 0:
            rem = total - (line_cost_by_metal.get('gold', 0.0) + line_cost_by_metal.get('silver', 0.0))
            if rem > 0.01:
                line_cost_by_metal['silver'] += rem
        # Cost
        dt = datetime.fromtimestamp(latest_recv_ms/1000.0, tz=timezone.utc).astimezone().date().isoformat()
        # Allocate per-metal cost
        metals_present = [m for m in ('gold','silver') if oz_by_metal.get(m,0.0) > 0]
        use_line = any(v > 0 for v in line_cost_by_metal.values())
        cost_alloc: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
        alloc_strategy = 'order-proportional'
        # For single-metal orders, prefer the order total even if some line prices were detected
        if len(metals_present) == 1 and total:
            cost_alloc[metals_present[0]] = total
            alloc_strategy = 'order-single-metal'
        elif use_line:
            cost_alloc = line_cost_by_metal.copy()
            alloc_strategy = 'line-item'
        else:
            denom = sum(oz_by_metal[m] for m in metals_present)
            for m in metals_present:
                cost_alloc[m] = (total * (oz_by_metal[m]/denom)) if denom > 0 else 0.0
            alloc_strategy = 'order-proportional'

        # Emit rows
        for metal in ('gold', 'silver'):
            oz = oz_by_metal.get(metal, 0.0)
            if oz <= 0:
                continue
            alloc = cost_alloc.get(metal, 0.0)
            cpo = (alloc / oz) if oz > 0 else 0.0
            metal_units = units_by_metal.get(metal, {})
            unit_count = sum(metal_units.values())
            cur_out = 'C$' if vendor in ('TD', 'Costco') else (cur or 'C$')
            rows_out.append({
                'vendor': vendor,
                'date': dt,
                'metal': metal,
                'currency': cur_out,
                'cost_total': round(alloc, 2),
                'cost_per_oz': round(cpo, 2),
                'order_id': oid,
                'subject': subject,
                'total_oz': round(oz, 3),
                'unit_count': format_qty(unit_count),
                'units_breakdown': format_breakdown(metal_units),
                'alloc': alloc_strategy,
            })

    # Write CSV
    out_path = getattr(args, 'out', 'out/metals/costs.csv')
    write_costs_csv(out_path, rows_out)
    print(f"wrote {out_path} rows={len(rows_out)}")
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
