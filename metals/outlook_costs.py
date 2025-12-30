"""
Extract per-order costs from Outlook Royal Canadian Mint (RCM) emails and merge into costs.csv.

Heuristics:
- Search Outlook messages for RCM (mint.ca) order confirmations/shipping.
- Group by order id (e.g., PO1616870); prefer Confirmation over Shipping over Request.
- Parse line items for unit sizes (supports '1/10-oz', '0.1 oz', '1 oz', grams) and quantities.
- Extract Total/Subtotal currency amount (fallback: largest currency in email body).
- Compute cost_per_oz = cost_total / total_oz.
- Focus: only emit GOLD rows for RCM (skip silver).

Usage:
  python -m metals.outlook_costs \
    --profile outlook_personal \
    --out out/metals/costs.csv
"""
from __future__ import annotations

import argparse
import re
from typing import Dict, List, Optional, Tuple

from core.auth import resolve_outlook_credentials
from core.constants import DEFAULT_OUTLOOK_TOKEN_CACHE, DEFAULT_REQUEST_TIMEOUT
from core.text_utils import html_to_text
from mail.outlook_api import OutlookClient

from .costs_common import (
    extract_order_amount,
    format_breakdown,
    format_qty,
    get_price_band,
    merge_costs_csv,
)
from .vendors import RCMParser

# Shared RCM parser instance
_rcm_parser = RCMParser()

# Subject classification for email priority ranking (delegate to parser)
SUBJECT_RANK = _rcm_parser.SUBJECT_RANK

_RCM_QUERIES = [
    'email.mint.ca',
    'Royal Canadian Mint',
    'order number PO',
    'Confirmation for order number',
]


def _classify_subject(subject: str) -> str:
    """Classify email subject for priority ranking."""
    cat, _ = _rcm_parser.classify_email(subject)
    return cat


def _extract_order_id(subject: str, body_text: str) -> Optional[str]:
    """Extract RCM order ID from subject or body."""
    return _rcm_parser.extract_order_id(subject, body_text)


def _extract_line_items(text: str) -> Tuple[List[Dict], List[str]]:
    """Extract line items using the shared RCM parser."""
    line_items, lines = _rcm_parser.extract_line_items(text)
    # Convert LineItem dataclass to dict format for backward compatibility
    items = [
        {'metal': item.metal, 'unit_oz': item.unit_oz, 'qty': item.qty, 'idx': item.idx}
        for item in line_items
    ]
    return items, lines


def _amount_near_item(lines: List[str], idx: int, *, metal: str = '', unit_oz: float = 0.0) -> Optional[Tuple[float, str]]:
    """Find a CAD amount near an item line using the shared RCM parser."""
    hit = _rcm_parser.extract_price_near_item(lines, idx, metal, unit_oz)
    if hit:
        return hit.amount, hit.kind
    return None


def _extract_confirmation_item_totals(text: str) -> List[float]:
    """Extract per-item 'Total $X CAD' amounts from a confirmation email body."""
    return _rcm_parser.extract_confirmation_totals(text)


def _fetch_rcm_message_ids(cli: OutlookClient) -> List[str]:
    """Fetch message IDs matching RCM search queries."""
    import requests
    base = f"{cli.GRAPH}/me/messages"
    ids: List[str] = []
    for q in _RCM_QUERIES:
        url = base + '?' + '&'.join([f'$search="{q}"', '$top=50'])
        for _ in range(3):
            r = requests.get(url, headers=cli._headers_search(), timeout=DEFAULT_REQUEST_TIMEOUT)
            if r.status_code >= 400:
                break
            data = r.json() or {}
            for m in data.get('value', []) or []:
                mid = m.get('id')
                if mid:
                    ids.append(mid)
            nxt = data.get('@odata.nextLink')
            if not nxt:
                break
            url = nxt
    return list(dict.fromkeys(ids))


def _filter_and_group_by_order(cli: OutlookClient, ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Filter to mint.ca sender and group messages by order ID."""
    by_order: Dict[str, Dict[str, str]] = {}
    for mid in ids:
        msg = cli.get_message(mid, select_body=True)
        frm = (((msg.get('from') or {}).get('emailAddress') or {}).get('address') or '').lower()
        if 'mint.ca' not in frm:
            continue
        body_html = ((msg.get('body') or {}).get('content') or '')
        body = html_to_text(body_html)
        sub = (msg.get('subject') or '')
        oid = _extract_order_id(sub, body)
        if not oid:
            continue
        recv = (msg.get('receivedDateTime') or '')
        cat = _classify_subject(sub)
        cur = by_order.get(oid)
        if (not cur) or (SUBJECT_RANK[cat] > SUBJECT_RANK.get(cur.get('cat', 'other'), 0)):
            by_order[oid] = {'id': mid, 'recv': recv, 'sub': sub, 'body': body, 'cat': cat}
    return by_order


def _try_upgrade_to_confirmation(cli: OutlookClient, oid: str, rec: Dict[str, str]) -> Dict[str, str]:
    """Try to find and use the Confirmation email for an order."""
    import requests as _req
    q = f'"Confirmation for order number {oid}"'
    try:
        ids = cli.search_inbox_messages(q, days=None, top=10, pages=2, use_cache=False)
    except Exception:  # noqa: S110 - skip on error
        ids = []
    if not ids:
        url = f"{cli.GRAPH}/me/messages?$search=\"Confirmation for order number {oid}\"&$top=10"
        r = _req.get(url, headers=cli._headers_search(), timeout=DEFAULT_REQUEST_TIMEOUT)
        if r.status_code < 400:
            data = r.json() or {}
            ids = [m.get('id') for m in (data.get('value') or []) if m.get('id')]
    if not ids:
        return rec
    chosen = None
    for mid in ids:
        try:
            mm = cli.get_message(mid, select_body=False)
        except Exception:  # noqa: S110 - skip on error
            continue
        sub = (mm.get('subject') or '').lower()
        if 'confirmation for order number' in sub:
            chosen = mid
            break
    best_mid = chosen or ids[0]
    try:
        m = cli.get_message(best_mid, select_body=True)
        body_html = ((m.get('body') or {}).get('content') or '')
        body = html_to_text(body_html)
        return {'id': best_mid, 'recv': (m.get('receivedDateTime') or ''), 'sub': (m.get('subject') or ''), 'body': body, 'cat': 'confirmation'}
    except Exception:  # noqa: S110 - fallback to original
        return rec


def _trim_disclaimer_lines(lines: List[str]) -> List[str]:
    """Trim disclaimer/footer sections from lines."""
    for i, ln in enumerate(lines):
        low = (ln or '').lower()
        if ('exceptions:' in low) or ('customer service solutions centre' in low) or ('returns' in low) or ('refund' in low):
            return lines[:i]
    return lines


def _summarize_ounces(items: List[Dict], metal_guess: str) -> Tuple[Dict[str, float], Dict[str, Dict[float, float]]]:
    """Summarize ounces and units per metal. Returns (oz_by_metal, units_by_metal)."""
    oz_by_metal: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
    units_by_metal: Dict[str, Dict[float, float]] = {'gold': {}, 'silver': {}}
    for it in items:
        m = (it.get('metal') or metal_guess or '').lower()
        if m not in oz_by_metal:
            continue
        uoz = float(it.get('unit_oz') or 0.0)
        qty = float(it.get('qty') or 1.0)
        oz_by_metal[m] += uoz * qty
        units = units_by_metal[m]
        units[uoz] = units.get(uoz, 0.0) + qty
    return oz_by_metal, units_by_metal


def _compute_confirmation_line_costs(
    body: str, gold_items: List[Dict], oid: str, sub: str, recv: str
) -> Tuple[float, List[Dict[str, str | float]]]:
    """Compute line costs from confirmation email 'Total $X CAD' sequences. Returns (line_cost, per_item_rows)."""
    totals_seq = _extract_confirmation_item_totals(body)
    line_cost = 0.0
    per_item_rows: List[Dict[str, str | float]] = []
    k = 0
    for it in gold_items:
        qty = float(it.get('qty') or 1.0)
        uoz = float(it.get('unit_oz') or 0.0)
        lb, ub = get_price_band('gold', uoz)
        chosen = None
        while k < len(totals_seq):
            v = float(totals_seq[k])
            k += 1
            if lb <= v <= ub:
                chosen = v
                break
        if chosen is not None:
            amt = float(chosen)
            line_cost += amt * max(qty, 1.0)
            per_item_rows.append({
                'vendor': 'RCM', 'date': (recv or '').split('T', 1)[0], 'metal': 'gold', 'currency': 'C$',
                'cost_total': round(amt, 2), 'cost_per_oz': round(amt / max(uoz * max(qty, 1.0), 1e-9), 2),
                'order_id': oid, 'subject': sub, 'total_oz': round(uoz * max(qty, 1.0), 3),
                'unit_count': format_qty(qty), 'units_breakdown': f"{uoz}ozx{format_qty(qty)}", 'alloc': 'line-item',
            })
    return line_cost, per_item_rows


def _compute_proximity_line_costs(gold_items: List[Dict], lines: List[str]) -> float:
    """Compute line costs using proximity-based price extraction."""
    line_cost = 0.0
    for it in gold_items:
        idx_line = min(int(it.get('idx') or 0), len(lines) - 1)
        hit = _amount_near_item(lines, idx_line, metal='gold', unit_oz=float(it.get('unit_oz') or 0.0))
        qty = float(it.get('qty') or 1.0)
        if hit:
            amt, kind = hit
            line_cost += float(amt) * max(qty, 1.0) if kind == 'unit' else float(amt)
    return line_cost


def _build_gold_row(
    oid: str, sub: str, recv: str, total_cost: float, oz: float, gold_units: Dict[float, float], line_cost: float
) -> Dict[str, str | float]:
    """Build a single aggregated gold row."""
    cpo = (total_cost / oz) if oz > 0 else 0.0
    unit_count = sum(gold_units.values()) if gold_units else 1.0
    breakdown_str = format_breakdown(gold_units) if gold_units else f"{round(oz, 3)}ozx1"
    return {
        'vendor': 'RCM', 'date': (recv or '').split('T', 1)[0], 'metal': 'gold', 'currency': 'C$',
        'cost_total': round(total_cost, 2), 'cost_per_oz': round(cpo, 2), 'order_id': oid, 'subject': sub,
        'total_oz': round(oz, 3), 'unit_count': format_qty(unit_count), 'units_breakdown': breakdown_str,
        'alloc': 'line-item' if line_cost > 0 else 'order-single-metal',
    }


def run(profile: str, out_path: str, days: int = 365) -> int:  # noqa: ARG001 - days reserved for future use
    client_id, tenant, token = resolve_outlook_credentials(profile, None, None, None)
    token = token or DEFAULT_OUTLOOK_TOKEN_CACHE
    if not client_id:
        raise SystemExit('No Outlook client_id configured; set it under [mail.<profile>] in credentials.ini')
    cli = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir='.cache')
    cli.authenticate()

    ids = _fetch_rcm_message_ids(cli)
    by_order = _filter_and_group_by_order(cli, ids)

    for oid, rec in list(by_order.items()):
        if rec.get('cat') != 'confirmation':
            by_order[oid] = _try_upgrade_to_confirmation(cli, oid, rec)

    if not by_order:
        print('no RCM orders found')
        return 0

    out_rows: List[Dict[str, str | float]] = []
    for oid, rec in by_order.items():
        sub, body, recv = rec['sub'], rec['body'], rec['recv']
        items, lines = _extract_line_items(body)
        lines_use = _trim_disclaimer_lines(lines)

        metal_guess = 'gold' if re.search(r'(?i)\bgold\b', body) else ('silver' if re.search(r'(?i)\bsilver\b', body) else '')
        oz_by_metal, units_by_metal = _summarize_ounces(items, metal_guess)

        # Fallback: if product name suggests 1/10 oz gold but no items parsed
        if oz_by_metal['gold'] == 0.0 and re.search(r'(?i)1\s*/\s*10\s*[- ]?oz', body):
            oz_by_metal['gold'] = 0.1
            units_by_metal['gold'][0.1] = 1.0

        gold_items = [it for it in items if (it.get('metal') or metal_guess or '').lower() == 'gold']

        # Try line-item pricing from confirmation email
        line_cost, per_item_rows = 0.0, []
        if rec.get('cat') == 'confirmation':
            line_cost, per_item_rows = _compute_confirmation_line_costs(body, gold_items, oid, sub, recv)

        # Fall back to proximity-based pricing
        if line_cost == 0.0:
            line_cost = _compute_proximity_line_costs(gold_items, lines_use)

        # Determine total cost
        cur_amt = extract_order_amount(body)
        if cur_amt and line_cost > 0:
            low, high = 0.6 * cur_amt[1], 1.05 * cur_amt[1]
            total_cost = line_cost if (low <= line_cost <= high) else cur_amt[1]
        else:
            total_cost = line_cost if line_cost > 0 else (cur_amt[1] if cur_amt else 0.0)

        if total_cost <= 0:
            continue

        if per_item_rows:
            out_rows.extend(per_item_rows)
        else:
            oz = oz_by_metal.get('gold', 0.0)
            if oz <= 0:
                continue
            out_rows.append(_build_gold_row(oid, sub, recv, total_cost, oz, units_by_metal.get('gold', {}), line_cost))

    if out_rows:
        merge_costs_csv(out_path, out_rows)
        print(f"merged {len(out_rows)} RCM row(s) into {out_path}")
    else:
        print('RCM messages found but no line-items/amounts parsed')
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description='Extract RCM costs from Outlook and merge into costs.csv')
    p.add_argument('--profile', default='outlook_personal')
    p.add_argument('--out', default='out/metals/costs.csv')
    p.add_argument('--days', type=int, default=365)
    args = p.parse_args(argv)
    return run(profile=getattr(args, 'profile', 'outlook_personal'), out_path=getattr(args, 'out', 'out/metals/costs.csv'), days=int(getattr(args, 'days', 365)))


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
