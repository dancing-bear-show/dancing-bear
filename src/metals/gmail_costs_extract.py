"""Order extraction and GmailCostExtractor class for Gmail precious metals cost parsing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from mail.config_resolver import resolve_paths_profile
from mail.gmail_api import GmailClient

from .cost_extractor import CostExtractor, MessageInfo, OrderData
from .costs_common import (
    extract_order_amount,
    format_breakdown,
    format_qty,
    write_costs_csv,
)
from .vendors_search import GMAIL_VENDORS, get_vendor_for_sender
from .gmail_costs_qty_items import _extract_line_items
from .gmail_costs_qty_price import _extract_amount_near_line

_ORDER_PAT = re.compile(r"(?i)order\s*(?:number|#)?\s*[:#]?\s*(\d{6,})")
_COSTCO_ORDER_PAT = re.compile(r"(?i)costco\.ca\s+order\D*(\d{6,})")
_CANCELLED_PAT = re.compile(r"(?i)\bcancel(?:led|ed)\b")

_QUERIES = [
    'from:noreply@td.com subject:"TD Precious Metals"',
    'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
    'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
    '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)',
    'cancel from:orderstatus@costco.ca',
    'cancel from:order-cancel@costco.ca',
]


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


def _is_cancelled(subject: str, from_header: str) -> bool:
    """Check if order was cancelled based on subject and sender."""
    s = f"{subject or ''} {from_header or ''}"
    return _CANCELLED_PAT.search(s) is not None


def _fetch_message_ids(client: GmailClient) -> List[str]:
    """Fetch and deduplicate message IDs from all vendor queries."""
    ids: List[str] = []
    for q in _QUERIES:
        ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
    return list(dict.fromkeys(ids))


def _is_costco_bulk_silver_total(vendor: str, metal: str, uoz: float, qty: float, val: float) -> bool:
    """True when a Costco silver unit price actually looks like a bulk-lot total, not a per-unit price."""
    return (
        vendor == 'Costco' and metal == 'silver' and uoz <= 1.05 and qty >= 10
        and (val / max(uoz, 1e-6)) > 150
    )


def _unit_hit_cost(hits: List[Tuple[float, str]], vendor: str, metal: str, uoz: float, qty: float) -> float:
    """Compute cost from 'unit'/'unknown' price hits (no 'total' hit was present)."""
    unit_vals = [a for (a, k) in hits if k in ('unit', 'unknown')]
    if not unit_vals:
        return 0.0
    val = max(unit_vals)
    if _is_costco_bulk_silver_total(vendor, metal, uoz, qty, val):
        return float(val)
    return float(val) * max(qty, 1.0)


def _line_cost_for_item(
    hits: List[Tuple[float, str]], vendor: str, metal: str, uoz: float, qty: float
) -> float:
    """Compute the line cost contribution for a single (metal, unit_oz) item's price hits."""
    amt_total = next((a for (a, k) in hits if k == 'total'), None)
    if amt_total is not None:
        return float(amt_total)
    return _unit_hit_cost(hits, vendor, metal, uoz, qty)


def _compute_line_costs(
    final_qty: Dict[Tuple[str, float], float],
    price_hits: Dict[Tuple[str, float], List[Tuple[float, str]]],
    vendor: str,
) -> Dict[str, float]:
    """Compute line-item costs per metal from price hits."""
    line_cost: Dict[str, float] = {'gold': 0.0, 'silver': 0.0}
    for (metal, uoz), qty in final_qty.items():
        hits = price_hits.get((metal, uoz), [])
        if not hits:
            continue
        line_cost[metal] += _line_cost_for_item(hits, vendor, metal, uoz, qty)
    return line_cost


def _allocate_costs(
    oz_by_metal: Dict[str, float],
    line_cost: Dict[str, float],
    total: float,
    vendor: str,
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
    alloc = {
        m: (total * (oz_by_metal[m] / denom)) if denom > 0 else 0.0
        for m in ('gold', 'silver')
    }
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
    price_hits: Dict[Tuple[str, float], List[Tuple[float, str]]],
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
    msgs: List[Tuple[str, int, str, str]],
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


def _aggregate_metals(
    final_qty: Dict[Tuple[str, float], float],
) -> Tuple[Dict[str, float], Dict[str, Dict[float, float]]]:
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
    dt = datetime.fromtimestamp(
        latest_recv_ms / 1000.0, tz=timezone.utc
    ).astimezone().date().isoformat()

    # Build output rows
    row_data = OrderRowData(
        oid=oid, vendor=vendor, subject=subject, cur=cur, dt=dt,
        oz_by_metal=oz_by_metal, units_by_metal=units_by_metal,
        cost_alloc=cost_alloc, alloc_strategy=alloc_strategy,
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
            received_ms=recv_ms,
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

    def run(self) -> int:  # NOSONAR - always returns 0; success-only tool, exit code reserved for subclasses
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

        self.last_row_count = len(out_rows)
        if out_rows:
            write_costs_csv(self.out_path, out_rows)
            print(f"wrote {self.out_path} rows={len(out_rows)}")
        else:
            print('messages found but no costs extracted')

        return 0
