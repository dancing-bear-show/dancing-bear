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

from .cost_extractor import CostExtractor, MessageInfo, OrderData
from .costs_common import extract_order_amount, format_breakdown, format_qty, get_price_band
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


class OutlookCostExtractor(CostExtractor):
    """Extract RCM costs from Outlook emails."""

    def __init__(self, profile: str, out_path: str, days: int = 365):
        super().__init__(profile, out_path, days)
        self.client: Optional[OutlookClient] = None

    def _authenticate(self) -> None:
        """Authenticate with Outlook."""
        client_id, tenant, token = resolve_outlook_credentials(self.profile, None, None, None)
        token = token or DEFAULT_OUTLOOK_TOKEN_CACHE
        if not client_id:
            raise SystemExit('No Outlook client_id configured; set it under [mail.<profile>] in credentials.ini')
        self.client = OutlookClient(client_id=client_id, tenant=tenant, token_path=token, cache_dir='.cache')
        self.client.authenticate()

    def _fetch_message_ids(self) -> List[str]:
        """Fetch message IDs matching RCM search queries."""
        ids: List[str] = []
        for q in _RCM_QUERIES:
            ids.extend(self._fetch_ids_for_query(q))
        return list(dict.fromkeys(ids))

    def _fetch_ids_for_query(self, query: str) -> List[str]:
        """Fetch message IDs for a single search query."""
        import requests
        base = f"{self.client.GRAPH}/me/messages"
        url = base + '?' + '&'.join([f'$search="{query}"', '$top=50'])
        ids: List[str] = []

        for _ in range(3):
            r = requests.get(url, headers=self.client._headers_search(), timeout=DEFAULT_REQUEST_TIMEOUT)
            if r.status_code >= 400:
                break

            data = r.json() or {}
            ids.extend(self._extract_ids_from_response(data))

            nxt = data.get('@odata.nextLink')
            if not nxt:
                break
            url = nxt

        return ids

    def _extract_ids_from_response(self, data: Dict) -> List[str]:
        """Extract message IDs from API response."""
        ids: List[str] = []
        for m in data.get('value', []) or []:
            mid = m.get('id')
            if mid:
                ids.append(mid)
        return ids

    def _get_message_info(self, msg_id: str) -> MessageInfo:
        """Get normalized message information."""
        msg = self.client.get_message(msg_id, select_body=True)
        frm = (((msg.get('from') or {}).get('emailAddress') or {}).get('address') or '').lower()

        # Filter to mint.ca sender
        if 'mint.ca' not in frm:
            return MessageInfo(
                msg_id=msg_id, subject='', from_header=frm,
                body_text='', received_date=''
            )

        body_html = ((msg.get('body') or {}).get('content') or '')
        body = html_to_text(body_html)
        sub = (msg.get('subject') or '')
        recv = (msg.get('receivedDateTime') or '')

        return MessageInfo(
            msg_id=msg_id, subject=sub, from_header=frm,
            body_text=body, received_date=recv
        )

    def _extract_order_id(self, msg: MessageInfo) -> Optional[str]:
        """Extract RCM order ID from message."""
        return _rcm_parser.extract_order_id(msg.subject, msg.body_text)

    def _select_best_message(self, messages: List[MessageInfo]) -> MessageInfo:
        """Select best message, preferring Confirmation over Shipping over Request."""
        best = messages[0]
        best_rank = 0

        for msg in messages:
            cat, _ = _rcm_parser.classify_email(msg.subject)
            rank = SUBJECT_RANK.get(cat, 0)
            if rank > best_rank:
                best = msg
                best_rank = rank

        # Try to upgrade to confirmation email if not already
        if best_rank < SUBJECT_RANK['confirmation']:
            upgraded = self._try_upgrade_to_confirmation(best)
            if upgraded:
                return upgraded

        return best

    def _try_upgrade_to_confirmation(self, msg: MessageInfo) -> Optional[MessageInfo]:
        """Try to find and use the Confirmation email for an order."""
        oid = _rcm_parser.extract_order_id(msg.subject, msg.body_text)
        if not oid:
            return None

        ids = self._search_confirmation_messages(oid)
        if not ids:
            return None

        best_mid = self._select_confirmation_message(ids)
        return self._fetch_confirmation_message(best_mid, msg.from_header)

    def _search_confirmation_messages(self, order_id: str) -> List[str]:
        """Search for confirmation messages for an order ID."""
        import requests as _req

        # Try using client search first
        from core.outlook.mail import SearchParams
        q = f'"Confirmation for order number {order_id}"'
        try:
            ids = self.client.search_inbox_messages(
                SearchParams(search_query=q, days=None, top=10, pages=2, use_cache=False)
            )
            if ids:
                return ids
        except Exception:  # nosec B110 - skip on error
            pass

        # Fallback to direct API call
        url = f"{self.client.GRAPH}/me/messages?$search=\"Confirmation for order number {order_id}\"&$top=10"
        r = _req.get(url, headers=self.client._headers_search(), timeout=DEFAULT_REQUEST_TIMEOUT)
        if r.status_code < 400:
            data = r.json() or {}
            return [m.get('id') for m in (data.get('value') or []) if m.get('id')]

        return []

    def _select_confirmation_message(self, ids: List[str]) -> str:
        """Select the best confirmation message from a list of IDs."""
        for mid in ids:
            try:
                mm = self.client.get_message(mid, select_body=False)
                sub = (mm.get('subject') or '').lower()
                if 'confirmation for order number' in sub:
                    return mid
            except Exception:  # nosec B112 - skip unreadable messages
                continue
        return ids[0]

    def _fetch_confirmation_message(self, msg_id: str, from_header: str) -> Optional[MessageInfo]:
        """Fetch confirmation message details."""
        try:
            m = self.client.get_message(msg_id, select_body=True)
            body_html = ((m.get('body') or {}).get('content') or '')
            body = html_to_text(body_html)
            return MessageInfo(
                msg_id=msg_id,
                subject=(m.get('subject') or ''),
                from_header=from_header,
                body_text=body,
                received_date=(m.get('receivedDateTime') or '')
            )
        except Exception:  # nosec B110 - fallback to None
            return None

    def _classify_vendor(self, from_header: str) -> str:
        """Classify vendor (always RCM for Outlook)."""
        return 'RCM'

    def _process_order_to_rows(self, order: OrderData) -> List[Dict[str, str | float]]:
        """Process a single RCM order into output rows."""
        # Use best message (already selected)
        msg = order.messages[0] if order.messages else None
        if not msg or not msg.body_text:
            return []

        # Extract items and compute metals
        items_data = self._extract_items_and_metals(msg.body_text)
        if not items_data:
            return []

        _, gold_items, oz_by_metal, units_by_metal, lines_use = items_data

        # Compute line costs
        is_confirmation = 'confirmation for order' in msg.subject.lower()
        line_cost, per_item_rows = self._compute_costs(
            msg, gold_items, oz_by_metal, lines_use, is_confirmation, order.order_id
        )

        # Determine total cost
        total_cost = self._determine_total_cost(msg.body_text, line_cost)

        if total_cost <= 0:
            return []

        # Build output rows
        return self._build_output_rows(
            per_item_rows, total_cost, oz_by_metal, units_by_metal,
            order.order_id, msg, line_cost
        )

    def _extract_items_and_metals(
        self, body: str
    ) -> Optional[Tuple[List[Dict], List[Dict], Dict[str, float], Dict[str, Dict[float, float]], List[str]]]:
        """Extract line items and compute metal summaries.

        Returns:
            (items, gold_items, oz_by_metal, units_by_metal, lines_trimmed) or None
        """
        items, lines = _rcm_parser.extract_line_items(body)

        # Convert LineItem dataclass to dict for backward compatibility
        items_dict = [
            {'metal': item.metal, 'unit_oz': item.unit_oz, 'qty': item.qty, 'idx': item.idx}
            for item in items
        ]

        lines_use = self._trim_disclaimer_lines(lines)

        # Infer metal from body
        if re.search(r'(?i)\bgold\b', body):
            metal_guess = 'gold'
        elif re.search(r'(?i)\bsilver\b', body):
            metal_guess = 'silver'
        else:
            metal_guess = ''

        oz_by_metal, units_by_metal = self._summarize_ounces(items_dict, metal_guess)

        # Fallback: if product name suggests 1/10 oz gold but no items parsed
        if abs(oz_by_metal['gold']) < 1e-9 and re.search(r'(?i)1\s*/\s*10\s*[- ]?oz', body):
            oz_by_metal['gold'] = 0.1
            units_by_metal['gold'][0.1] = 1.0

        gold_items = [
            it for it in items_dict
            if (it.get('metal') or metal_guess or '').lower() == 'gold'
        ]

        return items_dict, gold_items, oz_by_metal, units_by_metal, lines_use

    def _compute_costs(
        self,
        msg: MessageInfo,
        gold_items: List[Dict],
        oz_by_metal: Dict[str, float],
        lines_use: List[str],
        is_confirmation: bool,
        order_id: str
    ) -> Tuple[float, List[Dict[str, str | float]]]:
        """Compute line costs and per-item rows.

        Returns:
            (line_cost, per_item_rows)
        """
        line_cost = 0.0
        per_item_rows: List[Dict[str, str | float]] = []

        # Try line-item pricing from confirmation email
        if is_confirmation:
            line_cost, per_item_rows = self._compute_confirmation_line_costs(
                msg.body_text, gold_items, order_id, msg.subject, msg.received_date
            )

        # Fall back to proximity-based pricing
        if abs(line_cost) < 1e-9:
            line_cost = self._compute_proximity_line_costs(gold_items, lines_use)

        return line_cost, per_item_rows

    def _determine_total_cost(self, body: str, line_cost: float) -> float:
        """Determine total cost from order amount and line costs."""
        cur_amt = extract_order_amount(body)

        if cur_amt and line_cost > 0:
            low, high = 0.6 * cur_amt[1], 1.05 * cur_amt[1]
            if low <= line_cost <= high:
                return line_cost
            return cur_amt[1]

        if line_cost > 0:
            return line_cost
        return cur_amt[1] if cur_amt else 0.0

    def _build_output_rows(
        self,
        per_item_rows: List[Dict],
        total_cost: float,
        oz_by_metal: Dict[str, float],
        units_by_metal: Dict[str, Dict[float, float]],
        order_id: str,
        msg: MessageInfo,
        line_cost: float
    ) -> List[Dict[str, str | float]]:
        """Build output rows from processed data."""
        if per_item_rows:
            return per_item_rows

        oz = oz_by_metal.get('gold', 0.0)
        if oz <= 0:
            return []

        return [self._build_gold_row(
            order_id, msg.subject, msg.received_date,
            total_cost, oz, units_by_metal.get('gold', {}), line_cost
        )]

    def _summarize_ounces(
        self, items: List[Dict], metal_guess: str
    ) -> Tuple[Dict[str, float], Dict[str, Dict[float, float]]]:
        """Summarize ounces and units per metal."""
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
        self, body: str, gold_items: List[Dict], oid: str, sub: str, recv: str
    ) -> Tuple[float, List[Dict[str, str | float]]]:
        """Compute line costs from confirmation email 'Total $X CAD' sequences."""
        totals_seq = _rcm_parser.extract_confirmation_totals(body)
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
                    'vendor': 'RCM',
                    'date': (recv or '').split('T', 1)[0],
                    'metal': 'gold',
                    'currency': 'C$',
                    'cost_total': round(amt, 2),
                    'cost_per_oz': round(amt / max(uoz * max(qty, 1.0), 1e-9), 2),
                    'order_id': oid,
                    'subject': sub,
                    'total_oz': round(uoz * max(qty, 1.0), 3),
                    'unit_count': format_qty(qty),
                    'units_breakdown': f"{uoz}ozx{format_qty(qty)}",
                    'alloc': 'line-item',
                })

        return line_cost, per_item_rows

    def _compute_proximity_line_costs(self, gold_items: List[Dict], lines: List[str]) -> float:
        """Compute line costs using proximity-based price extraction."""
        line_cost = 0.0

        for it in gold_items:
            idx_line = min(int(it.get('idx') or 0), len(lines) - 1)
            hit = _rcm_parser.extract_price_near_item(
                lines, idx_line, metal='gold', unit_oz=float(it.get('unit_oz') or 0.0)
            )
            qty = float(it.get('qty') or 1.0)

            if hit:
                amt, kind = hit.amount, hit.kind
                line_cost += float(amt) * max(qty, 1.0) if kind == 'unit' else float(amt)

        return line_cost

    def _build_gold_row(
        self,
        oid: str,
        sub: str,
        recv: str,
        total_cost: float,
        oz: float,
        gold_units: Dict[float, float],
        line_cost: float
    ) -> Dict[str, str | float]:
        """Build a single aggregated gold row."""
        cpo = (total_cost / oz) if oz > 0 else 0.0
        unit_count = sum(gold_units.values()) if gold_units else 1.0
        breakdown_str = format_breakdown(gold_units) if gold_units else f"{round(oz, 3)}ozx1"

        return {
            'vendor': 'RCM',
            'date': (recv or '').split('T', 1)[0],
            'metal': 'gold',
            'currency': 'C$',
            'cost_total': round(total_cost, 2),
            'cost_per_oz': round(cpo, 2),
            'order_id': oid,
            'subject': sub,
            'total_oz': round(oz, 3),
            'unit_count': format_qty(unit_count),
            'units_breakdown': breakdown_str,
            'alloc': 'line-item' if line_cost > 0 else 'order-single-metal',
        }

    def _trim_disclaimer_lines(self, lines: List[str]) -> List[str]:
        """Trim disclaimer/footer sections from lines."""
        for i, ln in enumerate(lines):
            low = (ln or '').lower()
            if ('exceptions:' in low) or ('customer service solutions centre' in low) or \
               ('returns' in low) or ('refund' in low):
                return lines[:i]
        return lines


# Test helper functions
_TEST_EXTRACTOR_DEFAULTS = ('outlook_personal', 'out/metals/costs.csv')


def _fetch_rcm_message_ids(cli: OutlookClient) -> List[str]:
    """Fetch message IDs matching RCM search queries."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    extractor.client = cli
    return extractor._fetch_message_ids()


def _filter_and_group_by_order(cli: OutlookClient, ids: List[str]) -> Dict[str, Dict[str, str]]:
    """Filter to mint.ca sender and group messages by order ID."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    extractor.client = cli
    by_order: Dict[str, Dict[str, str]] = {}
    for msg_id in ids:
        msg = extractor._get_message_info(msg_id)
        oid = extractor._extract_order_id(msg)
        if oid and msg.body_text:
            cat, _ = _rcm_parser.classify_email(msg.subject)
            cur = by_order.get(oid)
            if (not cur) or (SUBJECT_RANK[cat] > SUBJECT_RANK.get(cur.get('cat', 'other'), 0)):
                by_order[oid] = {'id': msg.msg_id, 'recv': msg.received_date, 'sub': msg.subject, 'body': msg.body_text, 'cat': cat}
    return by_order


def _try_upgrade_to_confirmation(cli: OutlookClient, oid: str, rec: Dict[str, str]) -> Dict[str, str]:
    """Try to find and use the Confirmation email for an order."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    extractor.client = cli

    # Search for confirmation messages
    ids = extractor._search_confirmation_messages(oid)
    if not ids:
        return rec

    # Select best confirmation message
    best_mid = extractor._select_confirmation_message(ids)

    # Fetch confirmation message
    upgraded = extractor._fetch_confirmation_message(best_mid, 'email@mint.ca')

    # If upgrade successful, return the upgraded message
    if upgraded:
        cat, _ = _rcm_parser.classify_email(upgraded.subject)
        return {
            'id': upgraded.msg_id,
            'recv': upgraded.received_date,
            'sub': upgraded.subject,
            'body': upgraded.body_text,
            'cat': cat
        }

    # Otherwise return original
    return rec


def _trim_disclaimer_lines(lines: List[str]) -> List[str]:
    """Trim disclaimer/footer sections from lines."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._trim_disclaimer_lines(lines)


def _summarize_ounces(items: List[Dict], metal_guess: str) -> Tuple[Dict[str, float], Dict[str, Dict[float, float]]]:
    """Summarize ounces and units per metal."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._summarize_ounces(items, metal_guess)


def _compute_confirmation_line_costs(
    body: str, gold_items: List[Dict], oid: str, sub: str, recv: str
) -> Tuple[float, List[Dict[str, str | float]]]:
    """Compute line costs from confirmation email 'Total $X CAD' sequences."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._compute_confirmation_line_costs(body, gold_items, oid, sub, recv)


def _compute_proximity_line_costs(gold_items: List[Dict], lines: List[str]) -> float:
    """Compute line costs using proximity-based price extraction."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._compute_proximity_line_costs(gold_items, lines)


def _build_gold_row(
    oid: str, sub: str, recv: str, total_cost: float, oz: float, gold_units: Dict[float, float], line_cost: float
) -> Dict[str, str | float]:
    """Build a single aggregated gold row."""
    extractor = OutlookCostExtractor(*_TEST_EXTRACTOR_DEFAULTS)
    return extractor._build_gold_row(oid, sub, recv, total_cost, oz, gold_units, line_cost)


def run(profile: str, out_path: str, days: int = 365) -> int:
    """Run Outlook cost extraction."""
    extractor = OutlookCostExtractor(profile, out_path, days)
    return extractor.run()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description='Extract RCM costs from Outlook and merge into costs.csv')
    p.add_argument('--profile', default='outlook_personal')
    p.add_argument('--out', default='out/metals/costs.csv')
    p.add_argument('--days', type=int, default=365)
    args = p.parse_args(argv)
    return run(
        profile=getattr(args, 'profile', 'outlook_personal'),
        out_path=getattr(args, 'out', 'out/metals/costs.csv'),
        days=int(getattr(args, 'days', 365))
    )


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
