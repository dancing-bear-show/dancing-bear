"""Pipeline pattern for metals extraction workflows.

Uses the core pipeline pattern with processors and producers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.pipeline import RequestConsumer, ResultEnvelope, SafeProcessor, BaseProducer

from .extractors import MetalsAmount, OrderExtraction


# ============================================================================
# Request/Result Types
# ============================================================================

@dataclass
class ExtractRequest:
    """Request to extract metals from emails."""
    profile: str = "gmail_personal"
    days: int = 365
    provider: str = "gmail"  # gmail or outlook


@dataclass
class ExtractResult:
    """Result of metals extraction."""
    total: MetalsAmount
    orders: List[OrderExtraction] = field(default_factory=list)
    message_count: int = 0


@dataclass
class SpotPriceRequest:
    """Request to fetch spot prices."""
    metal: str  # gold or silver
    start_date: str  # YYYY-MM-DD
    end_date: Optional[str] = None


@dataclass
class SpotPrice:
    """Daily spot price."""
    date: str
    price_usd: float
    price_cad: float


@dataclass
class SpotPriceResult:
    """Result of spot price fetch."""
    metal: str
    prices: List[SpotPrice] = field(default_factory=list)


@dataclass
class PremiumRequest:
    """Request to calculate purchase premiums."""
    costs_path: str = "out/metals/costs.csv"
    spot_dir: str = "out/metals"


@dataclass
class PremiumResult:
    """Result of premium calculation."""
    metal: str
    avg_premium_pct: float
    orders: List[Dict[str, Any]] = field(default_factory=list)


# ============================================================================
# Consumers (type aliases using generic RequestConsumer)
# ============================================================================

ExtractRequestConsumer = RequestConsumer[ExtractRequest]
SpotPriceRequestConsumer = RequestConsumer[SpotPriceRequest]
PremiumRequestConsumer = RequestConsumer[PremiumRequest]


# ============================================================================
# Processors
# ============================================================================

class GmailExtractProcessor(SafeProcessor[ExtractRequest, ExtractResult]):
    """Extracts metals data from Gmail."""

    def _process_safe(self, request: ExtractRequest) -> ExtractResult:
        from mail.config_resolver import resolve_paths_profile
        from mail.gmail_api import GmailClient
        from .extractors import extract_amounts, extract_order_id, MetalsAmount

        cred, tok = resolve_paths_profile(
            arg_credentials=None,
            arg_token=None,
            profile=request.profile,
        )
        client = GmailClient(
            credentials_path=cred,
            token_path=tok,
            cache_dir=".cache",
        )
        client.authenticate()

        queries = [
            'from:noreply@td.com subject:"TD Precious Metals"',
            'from:TDPreciousMetals@tdsecurities.com "Your order has arrived"',
            'from:orderstatus@costco.ca subject:"Your Costco.ca Order Number"',
            '(from:email.mint.ca OR from:mint.ca OR from:royalcanadianmint.ca) (order OR confirmation OR receipt OR shipped OR invoice)',
        ]

        # Gather message IDs
        cand_ids: List[str] = []
        for q in queries:
            cand_ids.extend(client.list_message_ids(query=q, max_pages=20, page_size=100))
        cand_ids = list(dict.fromkeys(cand_ids))

        # Deduplicate by order ID, keeping latest message
        order_map: Dict[str, tuple] = {}
        for mid in cand_ids:
            msg = client.get_message(mid, fmt="full")
            hdrs = GmailClient.headers_to_dict(msg)
            sub = hdrs.get("subject", "")
            text = client.get_message_text(mid)
            oid = extract_order_id(sub, text) or mid
            recv_ms = int(msg.get("internalDate") or 0)
            cur = order_map.get(oid)
            if not cur or recv_ms > cur[1]:
                order_map[oid] = (mid, recv_ms, sub)

        # Extract amounts
        total = MetalsAmount()
        orders: List[OrderExtraction] = []
        for oid, (mid, recv_ms, sub) in order_map.items():
            text = client.get_message_text(mid)
            amounts = extract_amounts(text)
            total = total + amounts
            if amounts.has_metals():
                orders.append(OrderExtraction(
                    order_id=oid,
                    message_id=mid,
                    gold_oz=amounts.gold_oz,
                    silver_oz=amounts.silver_oz,
                    subject=sub,
                    date_ms=recv_ms,
                ))

        return ExtractResult(
            total=total,
            orders=orders,
            message_count=len(order_map),
        )


class OutlookExtractProcessor(SafeProcessor[ExtractRequest, ExtractResult]):
    """Extracts metals data from Outlook."""

    def _process_safe(self, request: ExtractRequest) -> ExtractResult:
        from core.auth import resolve_outlook_credentials
        from mail.outlook_api import OutlookClient
        from .extractors import extract_amounts, extract_order_id, MetalsAmount

        client_id, tenant, token_path = resolve_outlook_credentials(request.profile)
        if not all([client_id, tenant, token_path]):
            raise ValueError("Missing Outlook credentials")

        client = OutlookClient(
            client_id=client_id,
            tenant=tenant,
            token_path=token_path,
        )

        # Search for metals emails
        kql = "(TD Precious Metals) OR (Costco order) OR (Royal Canadian Mint)"
        messages = client.search_messages(kql, top=200)

        # Deduplicate and extract
        order_map: Dict[str, tuple] = {}
        for msg in messages:
            sub = msg.get("subject", "")
            body = msg.get("body", {}).get("content", "")
            oid = extract_order_id(sub, body) or msg.get("id", "")
            recv = msg.get("receivedDateTime", "")
            cur = order_map.get(oid)
            if not cur or recv > cur[1]:
                order_map[oid] = (msg.get("id"), recv, sub, body)

        total = MetalsAmount()
        orders: List[OrderExtraction] = []
        for oid, (mid, recv, sub, body) in order_map.items():
            amounts = extract_amounts(body)
            total = total + amounts
            if amounts.has_metals():
                orders.append(OrderExtraction(
                    order_id=oid,
                    message_id=mid,
                    gold_oz=amounts.gold_oz,
                    silver_oz=amounts.silver_oz,
                    subject=sub,
                ))

        return ExtractResult(
            total=total,
            orders=orders,
            message_count=len(order_map),
        )


# ============================================================================
# Producers
# ============================================================================

class ExtractProducer(BaseProducer):
    """Produces output from extraction results."""

    def _produce_success(self, payload: ExtractResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        total = payload.total
        print(f"gold_oz={total.gold_oz:.3f} silver_oz={total.silver_oz:.3f}")
        print(f"Processed {payload.message_count} messages, found {len(payload.orders)} orders with metals")

        if payload.orders:
            print("\nSample orders:")
            for order in payload.orders[:10]:
                print(f"  - {order.order_id}: gold={order.gold_oz:.3f} silver={order.silver_oz:.3f}")
