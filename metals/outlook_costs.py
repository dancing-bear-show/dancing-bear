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
  python -m mail.utils.outlook_metals_costs \
    --profile outlook_personal \
    --out out/metals/costs.csv
"""
from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.auth import resolve_outlook_credentials
from mail.outlook_api import OutlookClient


G_PER_OZ = 31.1035


def _strip_html(s: str) -> str:
    if not s:
        return ""
    t = html.unescape(s)
    t = re.sub(r"<\s*br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<\s*p\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _extract_order_id(subject: str, body_text: str) -> Optional[str]:
    s = subject or ""; b = body_text or ""
    m = re.search(r"(?i)\bPO\d{5,}\b", s) or re.search(r"(?i)\bPO\d{5,}\b", b)
    return m.group(0) if m else None


def _extract_line_items(text: str) -> Tuple[List[Dict], List[str]]:
    items: List[Dict] = []
    t = (text or '')
    # Normalize unicode
    t = t.replace('\u2011', '-')  # non-breaking hyphen
    t = t.replace('\u2013', '-')  # en dash
    t = t.replace('\u2014', '-')  # em dash
    t = t.replace('\u00A0', ' ')
    lines: List[str] = [l.strip() for l in t.splitlines() if l.strip()]

    # Support 1/10-oz, 0.1 oz, 1 oz, grams
    pat_frac = re.compile(r"(?i)\b(\d+)\s*/\s*(\d+)\s*[- ]?oz\b[^\n]*?\b(gold|silver)\b|\b(\d+)\s*/\s*(\d+)\s*[- ]?oz\b")
    pat_oz = re.compile(r"(?i)(?<!/)\b(\d+(?:\.\d+)?)\s*[- ]?oz\b[^\n]*?(?:\b(gold|silver)\b)?")
    pat_g = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*(g|gram|grams)\b[^\n]*?(?:\b(gold|silver)\b)?")

    def find_qty_near(idx: int) -> Optional[float]:
        # Scan a wider window for explicit quantities
        for d in range(0, 7):
            for j in (idx + d, idx - d):
                if d == 0:
                    j = idx
            if 0 <= j < len(lines):
                m = (
                    re.search(r"(?i)\bqty\s*[:#]?\s*(\d{1,3})\b", lines[j])
                    or re.search(r"(?i)\bquantity\s*[:#]?\s*(\d{1,3})\b", lines[j])
                    or re.search(r"(?i)\bx\s*(\d{1,3})\b", lines[j])
                )
                if m:
                    try:
                        n = int(m.group(1))
                        if 1 <= n <= 200:
                            return float(n)
                    except Exception:
                        pass  # nosec B110 - invalid quantity
        return None

    def infer_metal(ctx: str) -> str:
        ct = (ctx or '').lower()
        if 'gold' in ct:
            return 'gold'
        if 'silver' in ct:
            return 'silver'
        return ''

    for idx, ln in enumerate(lines):
        # 1/10-oz style
        for m in re.finditer(r"(?i)\b1\s*/\s*10\s*[- ]?oz\b", ln):
            metal = infer_metal(ln)
            qty = find_qty_near(idx) or 1.0
            items.append({'metal': metal or 'gold', 'unit_oz': 0.1, 'qty': qty, 'idx': idx})
        for m in pat_frac.finditer(ln):
            try:
                num = float(m.group(1) or m.group(4)); den = float(m.group(2) or m.group(5) or 1)
            except Exception:
                continue
            oz = num / max(den, 1.0)
            metal = (m.group(3) or '').lower()
            qty = find_qty_near(idx) or 1.0
            items.append({'metal': metal or '', 'unit_oz': oz, 'qty': qty, 'idx': idx})
        for m in pat_oz.finditer(ln):
            wt = float(m.group(1))
            metal = (m.group(2) or '').lower()
            qty = find_qty_near(idx) or 1.0
            items.append({'metal': metal or '', 'unit_oz': wt, 'qty': qty, 'idx': idx})
        for m in pat_g.finditer(ln):
            wt_g = float(m.group(1))
            metal = (m.group(3) or '').lower()
            qty = find_qty_near(idx) or 1.0
            items.append({'metal': metal or '', 'unit_oz': wt_g / G_PER_OZ, 'qty': qty, 'idx': idx})
    # Deduplicate items that mention both fractional/decimal sizes on the same line
    if items:
        buckets: Dict[Tuple[int, int], Dict] = {}
        for it in items:
            ukey = int(round(float(it.get('unit_oz') or 0.0) * 1000))
            idx_key = int(it.get('idx') or 0)
            k = (ukey, idx_key)
            cur = buckets.get(k)
            if not cur:
                buckets[k] = dict(it)
            else:
                # Keep the larger quantity; prefer explicit metal tag
                try:
                    if float(it.get('qty') or 1.0) > float(cur.get('qty') or 1.0):
                        cur['qty'] = it.get('qty')
                except Exception:
                    pass  # nosec B110 - invalid qty comparison
                if (it.get('metal') or '') and not (cur.get('metal') or ''):
                    cur['metal'] = it.get('metal')
        items = list(buckets.values())
    return items, lines


def _amount_near_item(lines: List[str], idx: int, *, metal: str = '', unit_oz: float = 0.0) -> Optional[Tuple[float, str]]:
    """Find a CAD amount near an item line.

    Returns (amount, kind) where kind is 'unit' or 'total'.
    Skips global totals: lines containing subtotal, tax, shipping, savings.
    """
    money_pat = re.compile(r"(?i)(?:C\$|CAD\s*\$|CAD\$|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2})?)")
    ban = re.compile(r"(?i)(subtotal|shipping|handling|tax|gst|hst|pst|savings|free\s+shipping|orders?\s+over|threshold)")

    best_total: Optional[Tuple[float, int]] = None  # (amt, distance)
    best_unit: Optional[Tuple[float, int]] = None
    # Scan forward only up to +8 lines from the item line
    for d in range(0, 21):
        j = idx + d
        if not (0 <= j < len(lines)):
            continue
        ln = lines[j] or ""
        low = ln.lower()
        if ban.search(low):
            continue
        for m in money_pat.finditer(ln):
            try:
                amt = float(m.group(1).replace(",", ""))
            except Exception:
                continue
            # Filter obvious non-item amounts based on expected ranges
            if (metal or '').lower() == 'gold':
                u = float(unit_oz or 0.0)
                if u <= 0.11:
                    if not (150.0 <= amt <= 2000.0):
                        continue
                elif u <= 0.26:
                    if not (300.0 <= amt <= 4000.0):
                        continue
                elif u <= 0.6:
                    if not (600.0 <= amt <= 7000.0):
                        continue
                else:
                    if not (1200.0 <= amt <= 20000.0):
                        continue
            if re.search(r"(?i)\btotal\b", ln):
                if (best_total is None) or (d < best_total[1]):
                    best_total = (amt, d)
            else:
                if (best_unit is None) or (d < best_unit[1]):
                    best_unit = (amt, d)
    if best_total:
        return best_total[0], 'total'
    if best_unit:
        return best_unit[0], 'unit'
    return None


def _extract_order_amount(text: str) -> Optional[Tuple[str, float]]:
    t = (text or '').replace('\u00A0', ' ')
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    money_pat = re.compile(r"(?i)(C\$|CAD\s*\$|CAD\$|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2})?)")

    def parse_amount(s: str) -> float:
        return float(s.replace(',', ''))

    for pref in ('total', 'subtotal'):
        for ln in lines:
            low = ln.lower()
            if pref in low:
                pos = low.find(pref)
                found = None
                for m in money_pat.finditer(ln):
                    if m.start() >= pos:
                        found = m; break
                if not found:
                    allm = list(money_pat.finditer(ln))
                    found = allm[-1] if allm else None
                if found:
                    cur = found.group(1).upper(); amt = parse_amount(found.group(2))
                    return cur, amt
    best: Optional[Tuple[str, float]] = None
    for ln in lines:
        for m in money_pat.finditer(ln):
            cur = m.group(1).upper(); amt = parse_amount(m.group(2))
            if (best is None) or (amt > best[1]):
                best = (cur, amt)
    return best


def _extract_confirmation_item_totals(text: str) -> List[float]:
    """Extract per-item 'Total $X CAD' amounts from a confirmation email body.

    Returns amounts in the order they appear. Intended to pair with items in sequence.
    """
    t = (text or '').replace('\u00A0', ' ')
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    amounts: List[float] = []
    pat = re.compile(r"(?i)\btotal\b[^\n]*?(?:C\$|CAD\s*\$|CAD\$|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+(?:\.[0-9]{2}))\s*CAD")
    ban = re.compile(r"(?i)(orders?\s+over|threshold|free\s+shipping|subtotal|savings)")
    for ln in lines:
        if ban.search(ln or ''):
            continue
        m = pat.search(ln or '')
        if m:
            try:
                val = float((m.group(1) or '0').replace(',', ''))
                amounts.append(val)
            except Exception:
                continue
    return amounts


def _merge_write(out_path: str, new_rows: List[Dict[str, str | float]]) -> None:
    p = Path(out_path)
    existing: List[Dict[str, str]] = []
    if p.exists():
        with p.open(newline='', encoding='utf-8') as f:
            r = csv.DictReader(f)
            for row in r:
                existing.append(row)
    # Build composite list and then prune redundant shipping rows when confirmations exist
    all_rows: List[Dict[str, str]] = []
    all_rows.extend(existing)
    all_rows.extend([{k: str(v) for k, v in r.items()} for r in new_rows])  # normalize types to str

    # Group by (vendor, order_id, metal)
    from collections import defaultdict
    groups: Dict[Tuple[str, str, str], List[Dict[str, str]]] = defaultdict(list)
    for r in all_rows:
        key = ((r.get('vendor') or '').upper(), r.get('order_id') or '', (r.get('metal') or '').lower())
        groups[key].append(r)

    pruned: List[Dict[str, str]] = []
    for k, rows in groups.items():
        # If any confirmation rows exist in this group, drop shipping-only rows
        conf = [r for r in rows if 'confirmation for order' in (r.get('subject') or '').lower()]
        if conf:
            # Keep only confirmations
            pruned.extend(conf)
        else:
            pruned.extend(rows)

    # Now dedupe within pruned list by (vendor|order_id|metal|cost_total|units_breakdown)
    def key2(d):
        return f"{(d.get('vendor') or '').upper()}|{d.get('order_id') or ''}|{(d.get('metal') or '').lower()}|{d.get('cost_total') or ''}|{d.get('units_breakdown') or ''}"
    idx2: Dict[str, Dict[str, str]] = {}
    for r in pruned:
        idx2[key2(r)] = r
    merged = list(idx2.values())
    # Write
    with p.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['vendor','date','metal','currency','cost_total','cost_per_oz','order_id','subject','total_oz','unit_count','units_breakdown','alloc'])
        w.writeheader(); w.writerows(merged)


def run(profile: str, out_path: str, days: int = 365) -> int:
    client_id, tenant, token = resolve_outlook_credentials(profile, None, None, None)
    token = token or '.cache/.msal_token.json'
    if not client_id:
        raise SystemExit('No Outlook client_id configured; set it under [mail.<profile>] in credentials.ini')
    cli = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir='.cache')
    cli.authenticate()

    # Broad search then filter sender
    import requests
    base = f"{cli.GRAPH}/me/messages"
    # Target terms common to RCM confirmations
    queries = [
        'email.mint.ca',
        'Royal Canadian Mint',
        'order number PO',
        'Confirmation for order number',
    ]

    ids: List[str] = []
    for q in queries:
        url = base + '?' + '&'.join([f'$search="{q}"', '$top=50'])
        for _ in range(3):
            r = requests.get(url, headers=cli._headers_search())  # nosec B113
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
    ids = list(dict.fromkeys(ids))

    # Filter to mint.ca sender and group by order id
    by_order: Dict[str, Dict[str, str]] = {}
    pref_rank = {'confirmation': 3, 'shipping': 2, 'request': 1, 'other': 0}
    def classify_subject(sub: str) -> str:
        s = (sub or '').lower()
        if 'confirmation for order' in s:
            return 'confirmation'
        if 'shipping confirmation' in s or 'was shipped' in s:
            return 'shipping'
        if 'we received your request' in s:
            return 'request'
        return 'other'

    for mid in ids:
        msg = cli.get_message(mid, select_body=True)
        frm = (((msg.get('from') or {}).get('emailAddress') or {}).get('address') or '').lower()
        if 'mint.ca' not in frm:
            continue
        body_html = ((msg.get('body') or {}).get('content') or '')
        body = _strip_html(body_html)
        sub = (msg.get('subject') or '')
        oid = _extract_order_id(sub, body)
        if not oid:
            continue
        recv = (msg.get('receivedDateTime') or '')
        cat = classify_subject(sub)
        cur = by_order.get(oid)
        if (not cur) or (pref_rank[cat] > pref_rank.get(cur.get('cat','other'),0)):
            by_order[oid] = {'id': mid, 'recv': recv, 'sub': sub, 'body': body, 'cat': cat}

    # Try to upgrade each order to use the Confirmation email when available
    def try_upgrade_to_confirmation(oid: str, rec: Dict[str, str]) -> Dict[str, str]:
        q = f'"Confirmation for order number {oid}"'
        try:
            ids = cli.search_inbox_messages(q, days=None, top=10, pages=2, use_cache=False)
        except Exception:
            ids = []
        # If nothing in Inbox, try global search across all messages
        if not ids:
            import requests as _req
            url = f"{cli.GRAPH}/me/messages?$search=\"Confirmation for order number {oid}\"&$top=10"
            r = _req.get(url, headers=cli._headers_search())  # nosec B113
            if r.status_code < 400:
                data = r.json() or {}
                ids = [m.get('id') for m in (data.get('value') or []) if m.get('id')]
        if ids:
            # Choose the one whose subject contains the confirmation phrase; fallback to first
            chosen = None
            for mid in ids:
                try:
                    mm = cli.get_message(mid, select_body=False)
                except Exception:
                    continue
                sub = (mm.get('subject') or '').lower()
                if 'confirmation for order number' in sub:
                    chosen = mid; break
            best_mid = chosen or ids[0]
            try:
                m = cli.get_message(best_mid, select_body=True)
                body_html = ((m.get('body') or {}).get('content') or '')
                body = _strip_html(body_html)
                return {
                    'id': best_mid,
                    'recv': (m.get('receivedDateTime') or ''),
                    'sub': (m.get('subject') or ''),
                    'body': body,
                    'cat': 'confirmation',
                }
            except Exception:
                return rec
        return rec

    for oid, rec in list(by_order.items()):
        if rec.get('cat') != 'confirmation':
            by_order[oid] = try_upgrade_to_confirmation(oid, rec)

    if not by_order:
        print('no RCM orders found')
        return 0

    out_rows: List[Dict[str, str | float]] = []
    for oid, rec in by_order.items():
        sub = rec['sub']; body = rec['body']; recv = rec['recv']
        items, lines = _extract_line_items(body)
        # Trim disclaimer/tail sections that contain non-item amounts (e.g., $500 free-shipping thresholds)
        cut_at = None
        for i, ln in enumerate(lines):
            low = (ln or '').lower()
            if ('exceptions:' in low) or ('customer service solutions centre' in low) or ('returns' in low) or ('refund' in low):
                cut_at = i
                break
        lines_use = lines[:cut_at] if cut_at is not None else lines
        # Default metal guess: prefer gold; only emit gold rows downstream
        metal_guess = 'gold' if re.search(r'(?i)\bgold\b', body) else ('silver' if re.search(r'(?i)\bsilver\b', body) else '')
        # Summarize ounces per metal
        oz_by_metal: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
        units_by_metal: Dict[str, Dict[float, float]] = {'gold': {}, 'silver': {}}
        for it in items:
            m = (it.get('metal') or metal_guess or '').lower()
            if m not in oz_by_metal:
                continue
            uoz = float(it.get('unit_oz') or 0.0); qty = float(it.get('qty') or 1.0)
            oz_by_metal[m] += uoz * qty
            units = units_by_metal[m]
            units[uoz] = units.get(uoz, 0.0) + qty

        # If still zero but product name suggests 1/10 oz gold, assume 0.1oz gold x1
        if oz_by_metal['gold'] == 0.0 and re.search(r'(?i)1\s*/\s*10\s*[- ]?oz', body):
            oz_by_metal['gold'] = 0.1
            units_by_metal['gold'][0.1] = 1.0

        # Try line-item pricing: for confirmation emails, first use explicit 'Total $X CAD' per item sequence
        line_cost = 0.0
        gold_items = [it for it in items if (it.get('metal') or metal_guess or '').lower() == 'gold']
        per_item_rows: List[Dict[str, str | float]] = []
        if rec.get('cat') == 'confirmation':
            totals_seq = _extract_confirmation_item_totals(body)
            k = 0
            for it in gold_items:
                qty = float(it.get('qty') or 1.0)
                uoz = float(it.get('unit_oz') or 0.0)
                # Expected price band by size
                lb, ub = 150.0, 20000.0
                if uoz <= 0.11:
                    lb, ub = 150.0, 1000.0
                elif uoz <= 0.26:
                    lb, ub = 300.0, 4000.0
                elif uoz <= 0.6:
                    lb, ub = 600.0, 7000.0
                # Find the next total in band
                chosen = None
                while k < len(totals_seq):
                    v = float(totals_seq[k]); k += 1
                    if lb <= v <= ub:
                        chosen = v; break
                if chosen is not None:
                    amt = float(chosen)
                    line_cost += amt * max(qty, 1.0)
                    # Emit a per-item row
                    per_item_rows.append({
                        'vendor': 'RCM',
                        'date': (recv or '').split('T',1)[0],
                        'metal': 'gold',
                        'currency': 'C$',
                        'cost_total': round(amt, 2),
                        'cost_per_oz': round(amt / max(uoz * max(qty, 1.0), 1e-9), 2),
                        'order_id': oid,
                        'subject': sub,
                        'total_oz': round(uoz * max(qty, 1.0), 3),
                        'unit_count': int(qty) if abs(qty - int(qty)) < 1e-6 else round(qty, 3),
                        'units_breakdown': f"{uoz}ozx{int(qty) if abs(qty - int(qty)) < 1e-6 else qty}",
                        'alloc': 'line-item',
                    })
        # If still no cost from sequence, fall back to proximity amounts
        if line_cost == 0.0:
            for it in gold_items:
                idx_line = int(it.get('idx') or 0)
                idx_line = min(idx_line, len(lines_use) - 1)
                hit = _amount_near_item(lines_use, idx_line, metal='gold', unit_oz=float(it.get('unit_oz') or 0.0))
                qty = float(it.get('qty') or 1.0)
                if hit:
                    amt, kind = hit
                    if kind == 'unit':
                        line_cost += float(amt) * max(qty, 1.0)
                    else:
                        line_cost += float(amt)

        # Fallback to order total when no line pricing was captured
        cur_amt = _extract_order_amount(body)
        # Choose line_cost when it looks consistent with order-level amount; otherwise fallback to order amount
        if cur_amt and line_cost > 0:
            low, high = 0.6 * cur_amt[1], 1.05 * cur_amt[1]
            total_cost = line_cost if (low <= line_cost <= high) else cur_amt[1]
        else:
            total_cost = line_cost if line_cost > 0 else (cur_amt[1] if cur_amt else 0.0)
        if total_cost <= 0:
            continue
        cur_out = 'C$'

        # If we produced per-item rows on confirmation, append them and skip aggregate
        if per_item_rows:
            out_rows.extend(per_item_rows)
        else:
            # Emit single aggregated gold row as fallback
            oz = oz_by_metal.get('gold', 0.0)
            if oz <= 0:
                continue
            cpo = (total_cost / oz) if oz > 0 else 0.0
            breakdown = []
            unit_count = 0.0
            for uoz, qty in sorted(units_by_metal.get('gold', {}).items()):
                unit_count += qty
                qty_disp = int(qty) if abs(qty - int(qty)) < 1e-6 else qty
                breakdown.append(f"{uoz}ozx{qty_disp}")
            if not breakdown:
                breakdown = [f"{round(oz,3)}ozx1"]
                unit_count = 1
            out_rows.append({
                'vendor': 'RCM',
                'date': (recv or '').split('T',1)[0],
                'metal': 'gold',
                'currency': cur_out,
                'cost_total': round(total_cost, 2),
                'cost_per_oz': round(cpo, 2),
                'order_id': oid,
                'subject': sub,
                'total_oz': round(oz, 3),
                'unit_count': int(unit_count) if abs(unit_count - int(unit_count)) < 1e-6 else round(unit_count, 3),
                'units_breakdown': ';'.join(breakdown),
                'alloc': 'line-item' if line_cost > 0 else 'order-single-metal',
            })

    if out_rows:
        _merge_write(out_path, out_rows)
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
