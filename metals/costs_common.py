"""Shared utilities for precious metals cost extraction from email."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.text_utils import normalize_unicode

from .constants import G_PER_OZ, COSTS_CSV_FIELDS, MONEY_PATTERN


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


def _find_money_on_line(line: str, keyword: str) -> Optional[Tuple[str, float]]:
    """Find money amount on a line containing keyword. Prefers amount after keyword."""
    low = line.lower()
    if keyword not in low:
        return None
    pos = low.find(keyword)
    matches = list(MONEY_PATTERN.finditer(line))
    if not matches:
        return None
    # Prefer match after keyword, else last match on line
    found = next((m for m in matches if m.start() >= pos), matches[-1])
    return found.group(1).upper(), parse_money_amount(found.group(2))


def extract_order_amount(text: str) -> Optional[Tuple[str, float]]:
    """Extract (currency, total_amount) from message text.

    Looks for lines like 'Total ($CAD) C$1,301.60' or 'Subtotal C$123.45'.
    Returns the first 'Total' if available, else 'Subtotal', else the largest amount.
    """
    t = (text or '').replace('\u00A0', ' ')
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]

    # Prefer Total, then Subtotal
    for keyword in ('total', 'subtotal'):
        for ln in lines:
            result = _find_money_on_line(ln, keyword)
            if result:
                return result

    # Fallback: largest amount found
    best: Optional[Tuple[str, float]] = None
    for ln in lines:
        for m in MONEY_PATTERN.finditer(ln):
            cur, amt = m.group(1).upper(), parse_money_amount(m.group(2))
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
    if not units:
        return ""
    parts = []
    for uoz, qty in sorted(units.items()):
        qty_disp = format_qty(qty)
        parts.append(f"{uoz}ozx{qty_disp}")
    return ';'.join(parts)


def _extract_from_pattern(
    m: re.Match,
    idx: int,
    metal_grp: int,
    qty_grp: int,
    unit_oz_fn,
) -> Optional[Dict]:
    """Extract item dict from a regex match. Returns None on parse failure."""
    try:
        unit_oz = unit_oz_fn(m)
    except (ValueError, TypeError, IndexError):
        return None
    gc = len(m.groups())
    metal = (m.group(metal_grp) or '').lower() if gc >= metal_grp else ''
    qty_str = m.group(qty_grp) if gc >= qty_grp else None
    qty = float(qty_str) if qty_str else 1.0
    return {'metal': metal, 'unit_oz': unit_oz, 'qty': qty, 'idx': idx}


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
    t = normalize_unicode(text or '')
    lines: List[str] = [ln.strip() for ln in t.splitlines() if ln.strip()]

    # Pattern configs: (pattern, metal_group, qty_group, unit_oz_extractor)
    configs = [
        (pat_frac, 3, 4, lambda m: float(m.group(1)) / max(float(m.group(2) or 1), 1.0)),
        (pat_oz, 2, 3, lambda m: float(m.group(1))),
        (pat_g, 3, 4, lambda m: float(m.group(1)) / G_PER_OZ),
    ]

    items: List[Dict] = []
    for idx, ln in enumerate(lines):
        for pat, metal_grp, qty_grp, unit_oz_fn in configs:
            for m in pat.finditer(ln):
                item = _extract_from_pattern(m, idx, metal_grp, qty_grp, unit_oz_fn)
                if item:
                    items.append(item)

    return items, lines


def write_costs_csv(out_path: str, rows: List[Dict[str, str | float]]) -> None:
    """Write costs CSV with standard fieldnames."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COSTS_CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)


def _group_key(r: Dict[str, str]) -> Tuple[str, str, str]:
    """Key for grouping rows by (vendor, order_id, metal)."""
    return (r.get('vendor') or '').upper(), r.get('order_id') or '', (r.get('metal') or '').lower()


def _dedup_key(r: Dict[str, str]) -> str:
    """Key for deduplicating rows."""
    return '|'.join([
        _group_key(r)[0], _group_key(r)[1], _group_key(r)[2],
        r.get('cost_total') or '', r.get('units_breakdown') or '',
    ])


def _is_confirmation(r: Dict[str, str]) -> bool:
    """Check if row is from a confirmation email."""
    return 'confirmation for order' in (r.get('subject') or '').lower()


def merge_costs_csv(out_path: str, new_rows: List[Dict[str, str | float]]) -> None:
    """Merge new rows into existing costs CSV, deduplicating by key fields."""
    p = Path(out_path)

    # Load existing rows
    existing: List[Dict[str, str]] = []
    if p.exists():
        with p.open(newline='', encoding='utf-8') as f:
            existing = list(csv.DictReader(f))

    # Combine and normalize to strings
    all_rows = existing + [{k: str(v) for k, v in r.items()} for r in new_rows]

    # Group by (vendor, order_id, metal) for pruning
    groups: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for r in all_rows:
        groups[_group_key(r)].append(r)

    # Prune: prefer confirmations over shipping-only rows, then dedupe
    seen: Dict[str, Dict[str, str]] = {}
    for rows in groups.values():
        conf = [r for r in rows if _is_confirmation(r)]
        for r in (conf or rows):
            seen[_dedup_key(r)] = r

    # Write
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COSTS_CSV_FIELDS)
        w.writeheader()
        w.writerows(seen.values())


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
