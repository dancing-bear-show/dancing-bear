"""Shared utilities for precious metals cost extraction from email."""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.text_utils import normalize_unicode

# Constants
G_PER_OZ = 31.1035

# CSV field names for costs output
COSTS_CSV_FIELDS = [
    'vendor', 'date', 'metal', 'currency', 'cost_total', 'cost_per_oz',
    'order_id', 'subject', 'total_oz', 'unit_count', 'units_breakdown', 'alloc',
]

# Money pattern: matches C$1,234.56 or CAD$1,234.56 or CAD $1,234.56 or $1,234.56
MONEY_PATTERN = re.compile(
    r"(?i)(C\$|CAD\s*\$|CAD\$|\$)\s*"
    r"([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2})?)"
)


def parse_money_amount(s: str) -> float:
    """Parse a money string like '1,234.56' to float."""
    return float(s.replace(',', ''))


def find_money(text: str) -> Optional[Tuple[str, float]]:
    """Find first money amount in text. Returns (currency, amount) or None."""
    m = MONEY_PATTERN.search(text or "")
    if m:
        cur = m.group(1).upper()
        amt = parse_money_amount(m.group(2))
        return cur, amt
    return None


def extract_order_amount(text: str) -> Optional[Tuple[str, float]]:
    """Extract (currency, total_amount) from message text.

    Looks for lines like 'Total ($CAD) C$1,301.60' or 'Subtotal C$123.45'.
    Returns the first 'Total' if available, else 'Subtotal', else the largest amount.
    """
    t = (text or '').replace('\u00A0', ' ')
    lines = [line.strip() for line in t.splitlines() if line.strip()]

    # Prefer Total, then Subtotal
    for pref in ('total', 'subtotal'):
        for ln in lines:
            low = ln.lower()
            if pref in low:
                pos = low.find(pref)
                found = None
                for m in MONEY_PATTERN.finditer(ln):
                    if m.start() >= pos:
                        found = m
                        break
                if found is None:
                    allm = list(MONEY_PATTERN.finditer(ln))
                    found = allm[-1] if allm else None
                if found:
                    cur = found.group(1).upper()
                    amt = parse_money_amount(found.group(2))
                    return cur, amt

    # Else take the largest currency number found
    best: Optional[Tuple[str, float]] = None
    for ln in lines:
        for m in MONEY_PATTERN.finditer(ln):
            cur = m.group(1).upper()
            amt = parse_money_amount(m.group(2))
            if not best or amt > best[1]:
                best = (cur, amt)
    return best


def get_price_band(metal: str, unit_oz: float) -> Tuple[float, float]:
    """Get expected price band (low, high) for a metal unit size."""
    if (metal or '').lower() == 'gold':
        if unit_oz <= 0.11:
            return 150.0, 2000.0
        elif unit_oz <= 0.26:
            return 300.0, 4000.0
        elif unit_oz <= 0.6:
            return 600.0, 7000.0
        else:
            return 1200.0, 20000.0
    # Silver or unknown - wide band
    return 10.0, 50000.0


def format_qty(qty: float) -> int | float:
    """Format quantity as int if whole, else float."""
    return int(qty) if abs(qty - int(qty)) < 1e-6 else qty


def format_breakdown(units: Dict[float, float]) -> str:
    """Format units dict {unit_oz: qty} as breakdown string like '1ozx3;0.1ozx2'."""
    parts = []
    for uoz, qty in sorted(units.items()):
        qty_disp = format_qty(qty)
        parts.append(f"{uoz}ozx{qty_disp}")
    return ';'.join(parts)


def extract_line_items_base(
    text: str,
    *,
    pat_frac: re.Pattern,
    pat_oz: re.Pattern,
    pat_g: re.Pattern,
) -> Tuple[List[Dict], List[str]]:
    """Base line item extraction. Returns (items, lines).

    Each item dict has: metal, unit_oz, qty, idx
    Patterns are passed in to allow customization per module.
    """
    items: List[Dict] = []
    t = normalize_unicode(text or '')
    lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]

    for idx, ln in enumerate(lines):
        for m in pat_frac.finditer(ln):
            try:
                num = float(m.group(1))
                den = float(m.group(2) or 1)
            except (ValueError, TypeError, IndexError):
                continue
            group_count = len(m.groups())
            metal = (m.group(3) or '').lower() if group_count >= 3 else ''
            qty_str = m.group(4) if group_count >= 4 else None
            qty = float(qty_str) if qty_str else 1.0
            unit_oz = num / max(den, 1.0)
            items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})

        for m in pat_oz.finditer(ln):
            try:
                unit_oz = float(m.group(1))
            except (ValueError, TypeError):
                continue
            group_count = len(m.groups())
            metal = (m.group(2) or '').lower() if group_count >= 2 else ''
            qty_str = m.group(3) if group_count >= 3 else None
            qty = float(qty_str) if qty_str else 1.0
            items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})

        for m in pat_g.finditer(ln):
            try:
                wt_g = float(m.group(1))
            except (ValueError, TypeError):
                continue
            group_count = len(m.groups())
            metal = (m.group(3) or '').lower() if group_count >= 3 else ''
            qty_str = m.group(4) if group_count >= 4 else None
            qty = float(qty_str) if qty_str else 1.0
            unit_oz = wt_g / G_PER_OZ
            items.append({'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx})

    return items, lines


def write_costs_csv(out_path: str, rows: List[Dict[str, str | float]]) -> None:
    """Write costs CSV with standard fieldnames."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COSTS_CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)


def merge_costs_csv(out_path: str, new_rows: List[Dict[str, str | float]]) -> None:
    """Merge new rows into existing costs CSV, deduplicating by key fields."""
    p = Path(out_path)
    existing: List[Dict[str, str]] = []
    if p.exists():
        with p.open(newline='', encoding='utf-8') as f:
            r = csv.DictReader(f)
            for row in r:
                existing.append(row)

    # Combine and normalize types
    all_rows: List[Dict[str, str]] = []
    all_rows.extend(existing)
    all_rows.extend([{k: str(v) for k, v in r.items()} for r in new_rows])

    # Group by (vendor, order_id, metal) for pruning
    from collections import defaultdict
    groups: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for r in all_rows:
        key = (
            (r.get('vendor') or '').upper(),
            r.get('order_id') or '',
            (r.get('metal') or '').lower(),
        )
        groups[key].append(r)

    # Prune: if confirmations exist, drop shipping-only rows
    pruned: List[Dict[str, str]] = []
    for rows in groups.values():
        conf = [r for r in rows if 'confirmation for order' in (r.get('subject') or '').lower()]
        if conf:
            pruned.extend(conf)
        else:
            pruned.extend(rows)

    # Dedupe by composite key
    def row_key(d: Dict[str, str]) -> str:
        return '|'.join([
            (d.get('vendor') or '').upper(),
            d.get('order_id') or '',
            (d.get('metal') or '').lower(),
            d.get('cost_total') or '',
            d.get('units_breakdown') or '',
        ])

    idx: Dict[str, Dict[str, str]] = {}
    for r in pruned:
        idx[row_key(r)] = r
    merged = list(idx.values())

    # Write
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COSTS_CSV_FIELDS)
        w.writeheader()
        w.writerows(merged)


__all__ = [
    'G_PER_OZ',
    'COSTS_CSV_FIELDS',
    'MONEY_PATTERN',
    'parse_money_amount',
    'find_money',
    'extract_order_amount',
    'get_price_band',
    'format_qty',
    'format_breakdown',
    'extract_line_items_base',
    'write_costs_csv',
    'merge_costs_csv',
]
